# ADR-0009: Workstation wrapper CLI (`3pa`) responsibilities and distribution

- **Status:** proposed
- **Date:** 2026-09-01
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

## Open questions

- Extend `3pa`, or a separate name/binary called `packages/workstation`?
- Language: Go (aligned with ADR-0008) vs extending the existing TS CLI.
- Should `3pa` manage the container runtime dependency (install Podman itself)?
- Windows support (is WSL2 mandatory)?

## Consequences

- **Positive:** A one-command experience for the developer; all the security setup
  in one place.
- **Negative / cost:** Maintaining a new binary, signing/notarization,
  auto-update.
