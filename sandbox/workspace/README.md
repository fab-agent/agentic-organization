# sandbox/workspace/

Department workspace image (ADR-0014, ADR-0018): one long-lived server-side
container per person, with the work toolchain baked in and the agent running in a
tmux session that survives client disconnects.

**Status: first cut.** The shell logic is tested (below). **The image itself has
not been built or run yet** — it was written in an environment without a Docker
daemon. Build it and run the smoke checks at the end before relying on it.

## Files

| File | Purpose |
|------|---------|
| `Dockerfile` | `node:22-bookworm-slim` + opencode + org plugin + managed config (as `sandbox/Dockerfile`), plus LibreOffice (writer/calc/impress), poppler, qpdf, Chromium, fonts, `tmux`, `tini`, optional Docling. Non-root `agent` (uid 10001). |
| `entrypoint.sh` | Main process. Scrubs `OPENCODE_*` env overrides (ADR-0011), creates `/workspace/{in,out}`, keeps the tmux session `agent` alive (recreates it if the tmux server dies), exits on SIGTERM. |
| `session-start.sh` | Idempotent creation of the tmux session with `remain-on-exit` (shared by the entrypoint and `attach.sh`). |
| `attach.sh` | Installed as `workspace-attach`. Restarts a dead agent pane, then `tmux attach`. The workspace-controller runs it via `docker exec -it`. |
| `chrome-headless.sh` | `chromium --headless=new --no-sandbox …`; exported as `CHROME_BIN`. |
| `compose.yaml` | Dev stand-in for the controller: internal-only network, egress proxy, home + files volumes, `cap_drop: ALL`. |
| `test_entrypoint.sh` | Behavioural test of the scripts without Docker (needs `tmux`). |

## Build and run

Build context is the **repo root**:

```sh
docker build -f sandbox/workspace/Dockerfile -t fab-workspace .
# with Docling (multi-GB: PyTorch + OCR models):
docker build -f sandbox/workspace/Dockerfile --build-arg WITH_DOCLING=1 -t fab-workspace:docling .

FABAGENT_BASE_URL=https://agents.example.com FABAGENT_TOKEN=<persona token> \
  docker compose -f sandbox/workspace/compose.yaml up -d --build
docker compose -f sandbox/workspace/compose.yaml exec workspace workspace-attach
```

Detach with `Ctrl-b d`; the agent keeps running. `docker compose … stop` then
`start` keeps `/home/agent` and `/workspace` (the suspend / resume of ADR-0018).

## Tests

```sh
sh sandbox/workspace/test_entrypoint.sh
```

Covers: session created, `OPENCODE_*` scrubbed except `OPENCODE_MODEL`,
`FABAGENT_TOKEN` passed through, `in/`+`out/` created, session recreated after
the tmux server dies, `attach.sh` recreating a missing session and respawning a
dead pane, prompt exit on SIGTERM. It uses a fake `opencode`, so it does not test
opencode, the plugin or the image.

## Smoke checks to run once the image is built

```sh
docker run --rm fab-workspace sh -c 'soffice --version && qpdf --version && pdftotext -v && chromium --version'
docker run --rm fab-workspace sh -c 'echo hi > /tmp/a.txt && soffice --headless --convert-to pdf --outdir /tmp /tmp/a.txt && ls /tmp/a.pdf'
docker run --rm fab-workspace chrome-headless --dump-dom about:blank
docker run --rm fab-workspace opencode --version
docker run --rm fab-workspace docling --version   # only when built with WITH_DOCLING=1
```

LibreOffice as uid 10001 with `cap_drop: ALL` needs a writable profile dir
(`$HOME/.config/libreoffice`, on the home volume) — if the conversion above fails
on a read-only rootfs, mount a tmpfs at `/home/agent/.config`.

## Known limitations

- **Token lifetime.** Persona tokens are short-lived (ADR-0007) but the container
  is long-lived. opencode config and the plugin read `FABAGENT_TOKEN` from the
  **environment once at start**, so a long session outlives its token. Needs
  `{file:}`-style token reading in `sandbox/opencode.json` and
  `packages/agent-plugin` plus a refresh writer (tracked in ADR-0018).
- **Chromium runs with `--no-sandbox`** (its own sandbox needs capabilities the
  container drops). The container, non-root user and egress proxy are the boundary.
- **Docling is opt-in** (image size). ADR-0015's ingest worker runs it server-side.
- No resource limits beyond `compose.yaml`; capacity planning is ADR-0014
  follow-up 4.
