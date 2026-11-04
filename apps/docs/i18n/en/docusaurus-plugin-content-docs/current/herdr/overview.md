---
sidebar_position: 1
---

# Herdr Client: Overview

> ADR-0026 (proposed) · Status: the server and `3pa` side are in the code; **not tested end to end in a real Herdr window**

The platform is being extended so that [Herdr](https://github.com/herdrdev) can be the daily client: the desktop app (the window) and its core (the layer that keeps terminals and agents running). The server gives a person a **layout and a set of mods chosen by their role**; `3pa` verifies the signature and installs that package into the user's Herdr folder. The opencode-based [workstation](/workstation/overview) keeps working; this path is added next to it, it does not replace it.

## Three parts

| Part | What it does | Page |
|---|---|---|
| **Signed workspace** | `GET /me/workspace` returns a signed layout + mod list for the role; `3pa workspace` installs it, verifies it and sends the server a count-only report | [Workspace](./workspace.md) |
| **Installation** | Linux/macOS/Windows user installers, a signed release chain, a vendor-neutral deployment contract | [Install and deploy](./install.md) |
| **Monitoring** | One view per company: service, audit, gateway, evaluation, signing key, sessions, clients | [Monitoring](./monitoring.md) |

## Security model in brief

- **Herdr mods are unrestricted code.** By Herdr's own documentation, mods run with the user's access, with no permission model and no layout or mod signing. So *what gets written to the user's folder* is decided entirely by the client (`3pa`), which installs only what the offline **root key** vouched for.
- **The root key is offline.** The server holds only a time-limited *signing certificate* signed by the root, and its key. A stolen server key is disabled with a revocation list (CRL); the steps are in the [recovery runbook](https://github.com/fab-agent/agentic-organization/blob/main/docs/runbooks/workspace-signing-key-recovery.md).
- **Profile selection is not authorisation.** The role only chooses which files a person is offered; every backend call re-checks person, company and role itself.
- **The server's policy gate fails closed.** If the policy infrastructure errors, the action is blocked; see [Policy engine](/workstation/policy-engine).

## Known limits

- Switching the layout in an open Herdr window (`layout.switch`) was written from Herdr's source; **it was not tried in a running window.**
- The default Herdr app folder on Windows (`%APPDATA%\herdr-app`) is a **guess**; override it with `--app-home`.
- The Windows binaries and installer are **not Authenticode-signed**; there is no MSI and no PATH handling.
- There is no decision yet on Herdr's own auto-update (ADR-0026 item 7).
- Workspace roles cannot prevent what a user does *on their own computer* (their own API keys, OS-level actions); that needs OS or network egress policy.
