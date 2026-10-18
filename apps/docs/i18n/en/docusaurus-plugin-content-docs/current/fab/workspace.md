---
sidebar_position: 2
---

# Workspace and Sync

There is **one workspace** for each human personnel record (ADR-0018). The person's single agent runs **inside** this space, as do the subagents it starts.

## Lifecycle

`creating → running ⇄ suspended`, plus `failed` and `deleted`.

- `suspended`: the home volume is kept, the container is stopped. the old token is revoked. `resume` **recreates** the container with a fresh token; files and the home directory stay, a running `tmux` session does not.
- `DELETE`: the container is removed, the volume is kept for **7 days**, then purged. A manager can restore it within this period.
- Idle: automatic suspension is **off by default** (enable with `WORKSPACE_IDLE_SUSPEND_MINUTES`). It cannot yet tell a running agent turn or flow from inactivity and only looks at file activity, so enabling it may stop running work. Turn/flow awareness and a per-company setting are planned.

## Who starts containers

Only a separate **`workspace-controller`** service has access to the container runtime. The backend does not mount `docker.sock`; so that a bug in the API does not become root on the host. The backend talks to it with a shared secret through the `WorkspaceRuntime` interface (`create`, `start`, `stop`, `remove`, `attach`, `status`, `list_files`) (`WORKSPACE_CONTROLLER_URL`, `WORKSPACE_CONTROLLER_SECRET`).

> **Current status (18 October 2026):** the controller (`workspace-controller/`) and a Docker runtime are written and were exercised with real Docker on one host: create, suspend/resume (with a fresh token), delete/restore, file list/upload/download, zero capabilities, non-root user, no direct internet, egress only through the filtering proxy. Housekeeping: a 15-minute job purges deleted workspaces after the 7-day retention; idle-suspend is opt-in. Not there yet: WebSocket attach, turn-aware idle suspension, a capacity model, a verb-filtering socket proxy in front of Docker, and a production deployment (compose service).

## API

| Request | Purpose |
|---|---|
| `POST /workspaces` | Create (idempotent per person) |
| `GET /workspaces/me` | My workspace and its state |
| `GET /workspaces` | List: manager/admin, own company |
| `POST /workspaces/{id}/resume` · `/suspend` | Resume / suspend |
| `DELETE /workspaces/{id}` | Delete (volume kept 7 days) |
| `POST /workspaces/{id}/attach-ticket` | *(planned)* Single-use attach ticket (~30 s) |
| `GET /workspaces/{id}/files?since=` | File manifest (path, size, sha256, mtime); only changes |
| `GET/PUT /workspaces/{id}/files/{path}` | Download a file / upload into `/workspace/in` |

A person controls only their own workspace; managers list, suspend and delete within their company. Every lifecycle call is written to the audit log.

## Attaching (WebSocket) — planned, not implemented

This is the design; there is no code yet. The client first gets an `attach-ticket` with its normal token; a long-lived token is not put in the URL (URLs end up in proxy logs). Binary frames are raw PTY bytes; text frames are JSON control messages (`resize`, `ping`, `exit`). A dropped connection does not kill the agent, it only detaches.

## The local folder: `fab sync` — narrowed by ADR-0022

ADR-0022 removed **automatic** sync: the local Assistant folder is not mirrored to the server; sending files is an explicit choice and downloads are safe downloads. The `fab sync` behaviour below is the older design (frozen `packages/tui`). A folder on the person's computer (for example the Desktop) is kept in step with the server-side workspace by `fab`:

- Everything the agent produces (`/workspace/out`) comes down into the folder.
- At the end of each session the agent writes a **session summary** in the form `summaries/YYYY-MM-DD-<topic>.md`.
- Files dropped into the folder's `in/` directory go up to the workspace.
- Outputs are one-way (server → computer) and versioned by name (`report-v2.xlsx`). `fab` **never overwrites** a file the person has edited locally; on conflict it keeps both.

## The workspace image

First version under `sandbox/workspace/`: LibreOffice, PDF tools and headless Chromium; same hardening as `sandbox/` (non-root user, default-deny egress, no host mounts). **Not yet run in Docker.**
