---
sidebar_position: 6
---

# `3pa`: The Workstation CLI

> ADR-0009 · `packages/cli` (`3pa`, TypeScript/tsx)

`3pa` is the developer persona's single entry point on the workstation: it signs in to the platform, starts opencode inside the managed sandbox, shows policy and audit state, and safely stops the running session.

---

## Commands

| Command | Description |
|---|---|
| `3pa init` | Setup wizard: backend URL, prerequisite check |
| `3pa login` | Pick a persona, get a workstation token pair → `~/.config/3pa/session.json` |
| `3pa logout` | Close the local session. `--revoke`: revoke on the server too |
| `3pa refresh` | Renew the persona access token |
| `3pa run` | Start opencode inside the managed sandbox |
| `3pa policy` | Show the effective policy rules for the persona |
| `3pa audit verify` | Verify the audit chain on the server |
| `3pa stop` | Stop the running sandbox session (signed command) |
| `3pa signal <signal>` | Send a signed control signal to the session |
| `3pa doctor` | Check sandbox prerequisites (Docker, network, image) |
| `3pa start` / `3pa status` | Start the platform with Docker / show its status |

---

## The session file

`~/.config/3pa/session.json`: persona identity, access + refresh token, backend URL. For test isolation it can be overridden with the `THREEPA_SESSION_FILE` environment variable. `sandbox/run.sh` reads this file.

---

## What `3pa run` does

1. Checks the validity of the access token and calls `refresh` if needed.
2. Fetches the [managed configuration](./managed-config.md) from `/.well-known/opencode` and verifies its signature.
3. Brings up the [sandbox](./sandbox.md) container + the egress proxy; mounts the project directory as `/work`.
4. Starts opencode inside the container with the gateway provider, the plugin and the guardrail prompt pre-installed.
5. Heartbeat loop: `POST /workstation/heartbeat` reports status and polls the [signed command channel](./injection-defense.md) (for example a remote `stop`).

---

## Heartbeat and command channel

While running, `3pa` sends a regular `POST /workstation/heartbeat`. The response carries pending **signed commands** (`PersonaCommand`); `3pa` verifies each with Ed25519, applies it and acknowledges it with `POST /workstation/commands/{id}/ack`. The owner can queue a command to a session from the panel with `POST /workstation/commands` (for example stopping a running sandbox remotely).

---

## Distribution

`release.yml` (ADR-0012) bundles `3pa` into a single file with esbuild and publishes it to GitHub Packages. The opencode version is pinned to **1.18.26**; compatibility matrix: `docs/architecture/version-compat.md`.

---

## Open items

- `3pa update`: self-update.
- A single binary `3pa` compiled with Go (to remove the Node dependency).
