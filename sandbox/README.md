# sandbox/

Workstation sandbox for running opencode with the org plugin (ADR-0002).

**Status: Phase 0 — roughest form.** Enough to demo the end-to-end loop
(gateway → upstream → tool events → audit). Not a security boundary yet.

## Files

| File | Purpose |
|------|---------|
| `Dockerfile` | Container image: `node:22-slim` + opencode + `packages/agent-plugin` + a baked-in managed config. Non-root `agent` user, project at `/work`. |
| `opencode.json` | opencode managed config baked into the image (`/etc/opencode/`). Points the `fabagent` provider at the gateway, loads the plugin, injects `base-prompt.md` as instructions, sets conservative `permission` defaults, disables `/share`. |
| `base-prompt.md` | Org operating rules injected into every session as instructions (ADR-0010): untrusted content is data not instructions, no unsolicited capability loading, no silent side effects, no secrets in outbound requests. |
| `entrypoint.sh` | Image entrypoint (ADR-0002): strips every `OPENCODE_*` env override (keeps `OPENCODE_MODEL`) so the host can't bypass the managed config, then `exec opencode`. |
| `run.sh` | Phase 0 stand-in for `3pa run` (ADR-0009): build image, `docker run` with only the current project mounted. **No egress restriction** — plain bridge network. |
| `compose.yaml` | `run.sh` + a mandatory egress proxy: the sandbox is on an `internal` network with no internet route, `egress/` is its only way out (ADR-0002 / ADR-0010 layer 3). |
| `egress/` | The filtering forward proxy (tinyproxy, `FilterDefaultDeny`). See `egress/README.md`. |

## Try it

The normal entry point is **`3pa run`** (`packages/cli`, ADR-0009), which does
the login-token + signed-config-verify + launch in one step:

```sh
3pa login
3pa run ~/code/my-project          # compose + egress by default
3pa run --no-egress ~/code/my-project
```

`3pa run` shells out to exactly the files below. To drive them directly:

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
- **Managed config** (ADR-0011) — `3pa run` fetches + Ed25519-verifies
  `/.well-known/opencode` and bind-mounts it over `/etc/opencode/opencode.json`;
  the baked copy is the offline / `--no-verify` fallback. Signing-key rotation
  supported (`wellknown_sign.rotate_key`). Still open: `OPENCODE_PERMISSION` /
  env-var bypass hardening and a plugin-side runtime assert.
- **Fail-closed heartbeat** — `3pa run` POSTs `/workstation/heartbeat` every 30 s
  and stops the sandbox in enforce mode (ADR-0009); `FABAGENT_FAIL_CLOSED=1`
  gives the plugin per-call fail-closed. Auto-revoke on stale heartbeat
  (ADR-0007) is the follow-up.
- **Isolation** (ADR-0002) — `cap_drop: ALL`, `no-new-privileges`, `pids_limit`,
  `mem_limit` / `cpus`, and `entrypoint.sh` scrubs `OPENCODE_*` overrides. Still
  open: a read-only rootfs, dropping the `docker.sock` reach, a check that
  opencode refuses to start outside the sandbox.
- macOS: needs a Podman/Colima VM; `run.sh` assumes a Linux container engine.
