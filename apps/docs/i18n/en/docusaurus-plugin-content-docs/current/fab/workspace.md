---
sidebar_position: 2
---

# Workspace and Sync

There is **one workspace** for each human personnel record (ADR-0018). The person's single agent runs **inside** this space, as do the subagents it starts.

## Lifecycle

`creating → running ⇄ suspended`, plus `failed` and `deleted`.

- `suspended`: the home volume is kept, the container is stopped. `resume` starts the container and reattaches to the still-running `tmux` session.
- `DELETE`: the container is removed, the volume is kept for **7 days**, then purged. A manager can restore it within this period.
- Idle: with no attached client and no running agent turn it is suspended after `idle_minutes` (default 30, per company). A running turn or a scheduled flow prevents suspension.

## Who starts containers

Only a separate **`workspace-controller`** service has access to the container runtime. The backend does not mount `docker.sock`; so that a bug in the API does not become root on the host. The backend talks to it with a shared secret through the `WorkspaceRuntime` interface (`create`, `start`, `stop`, `remove`, `attach`, `status`, `list_files`) (`WORKSPACE_CONTROLLER_URL`, `WORKSPACE_CONTROLLER_SECRET`).

> **Current status:** the interface only has a test-purpose `FakeRuntime` implementation (`WORKSPACE_RUNTIME=fake`). The real controller (Docker or a worker node, idle suspension, capacity model) has not been written yet; the contract is written in ADR-0018.

## API

| Request | Purpose |
|---|---|
| `POST /workspaces` | Create (idempotent per person) |
| `GET /workspaces/me` | My workspace and its state |
| `GET /workspaces` | List: manager/admin, own company |
| `POST /workspaces/{id}/resume` · `/suspend` | Resume / suspend |
| `DELETE /workspaces/{id}` | Delete (volume kept 7 days) |
| `POST /workspaces/{id}/attach-ticket` | Single-use attach ticket (~30 s) |
| `GET /workspaces/{id}/files?since=` | File manifest (path, size, sha256, mtime); only changes |
| `GET/PUT /workspaces/{id}/files/{path}` | Download a file / upload into `/workspace/in` |

A person controls only their own workspace; managers list, suspend and delete within their company. Every lifecycle call is written to the audit log.

## Attaching (WebSocket)

The client first gets an `attach-ticket` with its normal token; a long-lived token is not put in the URL (URLs end up in proxy logs). Binary frames are raw PTY bytes; text frames are JSON control messages (`resize`, `ping`, `exit`). A dropped connection does not kill the agent, it only detaches.

## The local folder: `fab sync`

A folder on the person's computer (for example the Desktop) is kept in step with the server-side workspace by `fab`:

- Everything the agent produces (`/workspace/out`) comes down into the folder.
- At the end of each session the agent writes a **session summary** in the form `summaries/YYYY-MM-DD-<topic>.md`.
- Files dropped into the folder's `in/` directory go up to the workspace.
- Outputs are one-way (server → computer) and versioned by name (`report-v2.xlsx`). `fab` **never overwrites** a file the person has edited locally; on conflict it keeps both.

## The workspace image

First version under `sandbox/workspace/`: LibreOffice, PDF tools and headless Chromium; same hardening as `sandbox/` (non-root user, default-deny egress, no host mounts). **Not yet run in Docker.**
