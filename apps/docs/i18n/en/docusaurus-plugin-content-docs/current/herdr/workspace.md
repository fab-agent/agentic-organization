---
sidebar_position: 2
---

# Signed Workspace

> ADR-0027 · ADR-0028 · ADR-0029 · ADR-0035 · ADR-0036 · ADR-0037 · ADR-0039 (all "proposed")

## Server: `GET /me/workspace`

Called by a signed-in user with `?company_id=`. The person is **not taken from the request**; the user's own human `Personnel` record in that company is used. A user with no such record, with an agent record, or asking for a company they are not a member of gets 404/403 and nothing is signed.

| Endpoint | Response |
|---|---|
| `GET /me/workspace?company_id=` | `{manifest, bootstrap}`: the signed envelope and first-install floors |
| `GET /me/workspace/files/{sha256}` | The file bytes; only for a hash in the caller's own profile |
| `GET /me/workspace/crl` | The root-signed cumulative revocation list (if one is published) |
| `POST /me/workspace/report` | The client's count-only report (below) |

- **Profiles** are defined in `catalog/profiles.json`; the first matching profile wins (keys `roles`, `departments`, `companies`). Any error in the file returns 503 `profiles_invalid` for **everyone**.
- **Every call takes a new generation number**, and the rate limit is claimed before anything is signed: **once per 10 seconds** per person (`429 try_again_later`, `Retry-After: 10`). A refused call changes nothing.
- `gateway_url` comes only from operator configuration (`https` required); it is never derived from request headers.
- **One human record per account:** if two human records are linked to one account the call returns 409; the invite flow cannot create that pair (covered by a race test). Existing duplicate records are **not repaired automatically**, and the database has no unique key for it.

## Client: `3pa workspace`

| Command | What it does |
|---|---|
| `3pa workspace sync` | Fetches the revocation list, verifies the manifest, downloads files into a staging folder checking size and SHA-256, and writes them to the Herdr app folder in a journalled (recoverable) transaction |
| `3pa workspace status` | Shows the difference between the installed package and the disk (missing, modified, extra) |
| `3pa workspace activate` | If the layout changed, asks the open Herdr window to switch with `herdr-app do layout.switch` |
| `3pa workspace report` | Sends the count-only report (automatic after `sync`; turn it off with `--no-report` or `THREEPA_NO_REPORT`) |

Key flags: `--root-pub` (or `FABAGENT_WORKSPACE_ROOT_PUB`), `--app-home` (or `HERDR_APP_HOME`), `--company`, `--re-enroll` (a new trust start for a different person or root).

Order of checks and guarantees:

1. **The root key is never fetched from the server**; the installer or MDM pins it.
2. **The revocation list is processed first** and saved at once.
3. The manifest's signature, certificate, validity window, person/company identity and **(epoch, generation) floors** are checked; an older generation is refused (rollback/replay protection). The TypeScript verifier gives the same verdicts as the Python one on a shared set of 60 test vectors.
4. Writing is a **journalled transaction**: an interrupted update is rolled back on the next run. Only one `sync` runs at a time (a lock file, not a kernel lock; its limits are written in ADR-0029).
5. Telemetry is written as off **before** the first launch.

**When does a new generation number come?** On every successful call. Re-signing identical content is not an error.

### Count-only report (drift)

After `sync` the client sends **counts only**: the installed `epoch`/`generation`, the number of missing, modified, extra and unmanaged files, and whether an update was left half done. No file names, paths or contents leave the machine. The report is a **claim, not proof**: the server uses it in no access, policy or signing decision, and a compromised client can send anything. One report per person is accepted every 30 seconds.

### Activating the layout

If the layout id changed, `sync` leaves an activation request; the launcher runs Herdr's own command in the background with `activate --wait 60 --quiet`. Herdr's `shared.json` is **never written**. A request is served once; if the user later switches to another layout on purpose, that is not fought. With no window the command fails and the request expires after 7 days. **This behaviour was written from the source code and not verified in a running window.**

## Key management

The root key is offline; the server holds a signing key and certificate. Key rotation, loss and theft are written step by step in [`docs/runbooks/workspace-signing-key-recovery.md`](https://github.com/fab-agent/agentic-organization/blob/main/docs/runbooks/workspace-signing-key-recovery.md). Important: changing the root is a new trust start (clients re-pin); **if the CRL number or the server epoch reaches 2^53-1 there is no supported recovery** (it needs a separate ADR and code).
