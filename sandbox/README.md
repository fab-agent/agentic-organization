# sandbox/

Workstation sandbox for running opencode with the org plugin (ADR-0002).

**Status: Phase 0 — roughest form.** Enough to demo the end-to-end loop
(gateway → upstream → tool events → audit). Not a security boundary yet.

## Files

| File | Purpose |
|------|---------|
| `Dockerfile` | Container image: `node:22-slim` + opencode + `packages/agent-plugin` + a baked-in managed config. Non-root `agent` user, project at `/work`. |
| `managed-settings.json` | opencode managed config baked into the image (`/etc/opencode/`). Points the `fabagent` provider at the gateway, loads the plugin, injects `base-prompt.md` as instructions, sets conservative `permission` defaults, disables `/share`. |
| `base-prompt.md` | Org operating rules injected into every session as instructions (ADR-0010): untrusted content is data not instructions, no unsolicited capability loading, no silent side effects, no secrets in outbound requests. |
| `run.sh` | Phase 0 stand-in for `3pa run` (ADR-0009): build image, `docker run` with only the current project mounted. **No egress restriction** — plain bridge network. |
| `compose.yaml` | `run.sh` + a mandatory egress proxy: the sandbox is on an `internal` network with no internet route, `egress/` is its only way out (ADR-0002 / ADR-0010 layer 3). |
| `egress/` | The filtering forward proxy (tinyproxy, `FilterDefaultDeny`). See `egress/README.md`. |

## Try it

1. Configure the org's upstream in the backend (Settings → AI Providers), or seed
   a `ProviderKey` with `base_url` set to your OpenAI-compatible endpoint.
2. Mint a persona token:
   `POST /gateway/persona-token?personnel_id=<agent personnel id>` (manager auth).
3. Run — either the bare container (no egress control):
   ```sh
   FABAGENT_BASE_URL=https://agents.example.com \
   FABAGENT_TOKEN=<token> \
   FABAGENT_MODEL=fabagent/qwen-turbo \
   sandbox/run.sh ~/code/my-project
   ```
   …or with the egress proxy (recommended — matches ADR-0002):
   ```sh
   FABAGENT_BASE_URL=https://agents.example.com \
   FABAGENT_TOKEN=<token> \
   EGRESS_ALLOWLIST=git.mycorp.com,artifactory.mycorp.com \
   PROJECT_DIR=~/code/my-project \
   docker compose -f sandbox/compose.yaml run --rm sandbox
   ```

## Not done yet (later phases)

- **Egress allowlist** (ADR-0010 layer 3) — `compose.yaml` + `egress/` provide it
  (internal network + `FilterDefaultDeny` proxy); the bare `run.sh` does not.
  Still open: per-company vs per-project allowlist scoping, and output scanning
  (layer 6).
- **Signature verification** of the config/policy bundle (ADR-0011).
- **Fail-closed heartbeat** — stop opencode when gateway/audit is unreachable
  (ADR-0006). Today the plugin only warns (`FABAGENT_FAIL_CLOSED=1` aborts
  individual tool calls but nothing supervises the session).
- **Credential hygiene** — `run.sh` mounts only the project dir, but does not yet
  scrub `OPENCODE_*` override env vars or drop capabilities.
- macOS: needs a Podman/Colima VM; `run.sh` assumes a Linux container engine.
