# sandbox/

Workstation sandbox for running opencode with the org plugin (ADR-0002).

**Status: Phase 0 — roughest form.** Enough to demo the end-to-end loop
(gateway → upstream → tool events → audit). Not a security boundary yet.

## Files

| File | Purpose |
|------|---------|
| `Dockerfile` | Container image: `node:22-slim` + opencode + `packages/agent-plugin` + a baked-in managed config. Non-root `agent` user, project at `/work`. |
| `managed-settings.json` | opencode managed config baked into the image (`/etc/opencode/`). Points the `fabagent` provider at the gateway, loads the plugin, sets conservative `permission` defaults, disables `/share`. |
| `run.sh` | Phase 0 stand-in for `3pa run` (ADR-0009): build image, `docker run` with only the current project mounted. |

## Try it

1. Configure the org's upstream in the backend (Settings → AI Providers), or seed
   a `ProviderKey` with `base_url` set to your OpenAI-compatible endpoint.
2. Mint a persona token:
   `POST /gateway/persona-token?personnel_id=<agent personnel id>` (manager auth).
3. Run:
   ```sh
   FABAGENT_BASE_URL=https://agents.example.com \
   FABAGENT_TOKEN=<token> \
   FABAGENT_MODEL=fabagent/qwen-turbo \
   sandbox/run.sh ~/code/my-project
   ```

## Not done yet (later phases)

- **Egress-proxy + allowlist** (ADR-0010) — this v0 uses a plain bridge network.
- **Signature verification** of the config/policy bundle (ADR-0011).
- **Fail-closed heartbeat** — stop opencode when gateway/audit is unreachable
  (ADR-0006). Today the plugin only warns (`FABAGENT_FAIL_CLOSED=1` aborts
  individual tool calls but nothing supervises the session).
- **Credential hygiene** — `run.sh` mounts only the project dir, but does not yet
  scrub `OPENCODE_*` override env vars or drop capabilities.
- macOS: needs a Podman/Colima VM; `run.sh` assumes a Linux container engine.
