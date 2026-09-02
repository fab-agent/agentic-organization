# ADR-0009: Workstation wrapper CLI (`3pa`) responsibilities and distribution

- **Status:** accepted (extend the TS CLI; `run` / `doctor` implemented, rest pending)
- **Date:** 2026-09-01 (accepted 2026-09-02)
- **Related:** ADR-0001, ADR-0002, ADR-0007, ADR-0011

## Context and problem

ADR-0001 (opencode client) + ADR-0002 (sandbox) + ADR-0004 (gateway) + ADR-0007
(identity) require a "glue": a single command the developer runs. Today
`packages/cli` (`3pa`) is only a Docker install wrapper (`init` / `start` /
`status`).

## Decision (proposed)

Extend `3pa` into a **workstation agent launcher** (or a separate
`packages/workstation` — an open question):

| Command | Job |
|---------|-----|
| `3pa login` | Platform identity → select persona → get a short-lived token (ADR-0007) |
| `3pa run [project]` | Bring up the sandbox container → inject the managed opencode config + org plugin → start the opencode TUI |
| `3pa policy` | Fetch/show the active policy from the server, verify its signature (ADR-0011) |
| `3pa audit verify` | Local buffer + server chain status |
| `3pa doctor` | Container runtime, egress-proxy, gateway reachability, token validity |
| `3pa update` | Update itself + the pinned opencode version |

**Responsibilities:**

- Fetches the **signed** config + policy from the server, verifies the signature,
  and refuses to run if it does not verify.
- Sets up the sandbox (ADR-0002): mounts, egress allowlist, resource limits.
- Writes the opencode managed config to `/etc/opencode/` **inside the container**
  (not on the host — the user can edit the host config, ADR-0003).
- Injects the token only into the container environment.
- Heartbeat: periodically reports "I'm alive + sandbox digest" to the gateway.
- Stops opencode if the gateway/audit is unreachable (fail-closed).

**Distribution:** a single static binary (Go — the same toolchain as ADR-0008),
Homebrew / `.deb` / direct download; can be pushed via enterprise MDM. Versioning
in ADR-0012.

## Implementation status (2026-09-02)

| Command | State |
|---------|-------|
| `3pa login` | done (ADR-0007) |
| `3pa run [project]` | **done** — `packages/cli/src/commands/run.ts`. Preflight: gateway + persona-token check (fail-closed), then fetch + Ed25519-verify `/.well-known/opencode` (`src/utils/wellknown.ts`), TOFU-pin the key id in the session, read `x-fabagent.fail_closed`. Launch: `docker compose -f sandbox/compose.yaml run --rm sandbox` (`src/utils/sandbox.ts` locates the assets; `FABAGENT_SANDBOX_DIR` overrides) with the token / model / project / `EGRESS_ALLOWLIST` injected only into the container env. A 30 s gateway heartbeat warns, and in enforce mode stops the sandbox, when the gateway goes unreachable. `--no-egress` falls back to `sandbox/run.sh`. |
| `3pa doctor` | **done** — `src/commands/doctor.ts`: container runtime, sandbox assets, session, gateway + token, signed config. |
| `3pa policy` / `audit verify` / `update` | not started |

**Resolved:** extend the existing TS CLI (not a new Go binary yet) — it already
has `login`; a Go rewrite waits for the ADR-0008 TUI. Sandbox asset bundling and
a signed release are ADR-0012.

**Still open:**

- `3pa` writing the verified config into `/etc/opencode/` **inside the container**
  (today the image bakes a static `managed-settings.json`; `run` only verifies
  the served bundle, it does not yet inject it — ADR-0011).
- A dedicated `/workstation/heartbeat` endpoint (liveness + sandbox digest into
  the audit) vs. the current `/v1/models` probe — feeds ADR-0007 auto-revoke.
- Should `3pa` manage the container runtime dependency (install Podman itself)?
- Windows support (is WSL2 mandatory)?

## Consequences

- **Positive:** A one-command experience for the developer; all the security setup
  in one place.
- **Negative / cost:** Maintaining a new binary, signing/notarization,
  auto-update.
