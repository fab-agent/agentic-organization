# ADR-0018: Workspace lifecycle API and attach protocol

- **Status:** proposed
- **Date:** 2026-09-29
- **Deciders:** Fabrika / fab.engineering
- **Related:** ADR-0002, ADR-0004, ADR-0005, ADR-0006, ADR-0007, ADR-0010, ADR-0014 (follow-ups 2 and 4)

## Context and problem

ADR-0014 decides that every person gets a long-lived, server-side workspace
container and that the `fab` terminal client (`packages/tui`) attaches to it.
It leaves the contract open: how a workspace is created, attached to,
suspended and resumed, how the client authenticates, and who is allowed to start
containers. `fab` today runs its agent pane on a *local* PTY; this ADR defines
what replaces that transport.

## Decision

### 1. Who starts containers: a separate `workspace-controller` service

**Decided (option A).** A small, single-purpose `workspace-controller` service is
the only component with container-runtime access. The backend never mounts
`/var/run/docker.sock` (an API bug must not become host root). It calls the
controller over the internal network through a `WorkspaceRuntime` interface
(`create`, `start`, `stop`, `remove`, `attach`, `status`, `list_files`),
authenticated with a shared secret (`WORKSPACE_CONTROLLER_URL`,
`WORKSPACE_CONTROLLER_SECRET`). It ships as one more compose service today.

Hardening of the controller itself, since it is the new privileged component:
reach Docker through a **socket proxy that allows only the verbs it needs**
(create / start / stop / rm / exec, no privileged or host-mount options) or use
rootless Podman; validate every input as an ID from the backend, never a free
path or image name; keep it free of user-facing endpoints.

The interface is multi-host-ready: moving to one controller per worker host
with mTLS (the former option B) later replaces the authentication and adds a
placement table, with no change to the API in section 3.

### 2. Workspace model

One workspace per human `Personnel` (`personnel_id`). The person's single agent
(ADR-0019) runs **inside** it, together with any subagents it starts. The agent
gets a persona token (ADR-0007) minted by the backend when the session starts and
injected as `FABAGENT_TOKEN` / `FABAGENT_BASE_URL`, exactly as `sandbox/` does;
runs it spawns receive narrower, derived tokens. A token never carries more than
the owning person's scope.

State machine: `creating → running ⇄ suspended`, plus `failed` and `deleted`.
`suspended` keeps the home volume and stops the container; `resume` starts it and
re-attaches to the still-running multiplexer session (see 4).

Container profile = `sandbox/compose.yaml` hardening (non-root, `cap_drop: ALL`,
`no-new-privileges`, pid/mem/cpu limits, **internal network only, egress through
the filtering proxy**, no host mounts) plus the work toolchain from ADR-0014.
Files the agent produces live under `/workspace/out` on a per-person volume.

### 3. REST API (backend, JWT-authenticated like the rest of `/api`)

| Method & path | Purpose |
|---|---|
| `POST /workspaces` | Create (idempotent per person): returns the workspace. |
| `GET /workspaces/me` | The caller's workspace and state. |
| `GET /workspaces` | List — managers/admins, scoped to their company. |
| `POST /workspaces/{id}/resume` | `suspended → running`. |
| `POST /workspaces/{id}/suspend` | `running → suspended` (also done by idle timer). |
| `DELETE /workspaces/{id}` | Remove the container; the volume is kept for **7 days**, then purged. A manager can restore it within that window. |
| `POST /workspaces/{id}/attach-ticket` | Mint a single-use attach ticket (see 4). |
| `GET /workspaces/{id}/files` | List `/workspace/out` as a manifest (`path`, `size`, `sha256`, `mtime`); `?since=<cursor>` returns only changes, so `fab` can sync the person's local folder incrementally (ADR-0019 §8). |
| `GET /workspaces/{id}/files/{path}` | Download one file (streamed, size-capped). |
| `PUT /workspaces/{id}/files/{path}` | Upload into `/workspace/in`. |

Authorisation: a person controls only their own workspace; managers can list,
suspend and delete within their company. Every lifecycle call goes through
`log_action` (ADR-0006) with actor, workspace and resulting state.

### 4. Attach protocol (WebSocket)

`GET /workspaces/{id}/attach?ticket=<t>` upgrades to a WebSocket.

- **Ticket, not bearer token in the URL.** The client first calls
  `attach-ticket` with its normal token and receives a random, single-use ticket
  valid for ~30 s. URLs end up in proxy logs; long-lived tokens must not.
- **Framing.** Binary frames = raw PTY bytes in both directions. Text frames =
  JSON control messages, initially `{"type":"resize","cols":N,"rows":N}` and
  `{"type":"ping"}`. Server → client control: `{"type":"exit","code":N}`.
- **Session persistence.** Inside the container the agent runs in a `tmux`
  (or `dtach`) session; attach is `tmux attach`. A dropped connection detaches,
  it does not kill the agent. This is why `fab` needs no persistence code of its
  own (see ADR-0014 spike outcome).
- **Idle.** Attached clients ping every 20 s. No attached client and no
  running agent turn for `idle_minutes` (default 30, per company) → `suspend`.
  A running agent turn or scheduled flow blocks suspension.

### 5. Client changes (`packages/tui`)

`pty.rs` keeps its `Pty` engine (input encoding, vt100 rendering, resize) and
gains a second byte transport: WebSocket instead of a local `portable-pty`.
`fab` gets `Create → Attach` on first run, shows workspace state in the
sidebar, and lists `/workspace/out` in the files strip.

## Options considered

- **Docker socket in the API container.** Simplest; rejected (root on the host
  from any API compromise).
- **SSH into the container** (herdr-style remote mode). Reuses existing
  tooling, but needs key distribution per person and an SSH endpoint through the
  same egress and audit path. WebSocket over the existing HTTPS entrypoint and
  JWT/ticket auth is one fewer moving part. Revisit if raw SSH access is needed.
- **Bearer token in the WebSocket query string.** Rejected (logging), see 4.

## Consequences

- **Positive:** one hardened, auditable path for every department; sessions
  survive disconnects; the API never touches the container runtime directly.
- **Negative / cost:** a new component (the runtime controller) to build and
  operate; capacity scales with head count (ADR-0014 follow-up 4: this ADR only
  supplies the suspend hook).
- **Accepted residual risk:** files in workspaces are company documents held
  server-side; the boundary is the container profile in 2 plus the egress proxy.

## Decisions taken on the open questions

1. **Controller placement:** separate `workspace-controller` service (section 1).
2. **Retention:** a deleted workspace's volume is kept **7 days**, then purged.
   Audit logs (ADR-0006) are kept independently; the volume exists so that
   material can still be recovered when someone asks after the fact.
3. **Persona binding:** one agent persona per person, created with the workspace;
   subagents are runs, not personas — see ADR-0019.

## Open question

1. **Windows clients:** WebSocket attach works everywhere; confirm we do not need
   raw SSH for any department.

## Follow-ups

1. `sandbox/workspace/` image: first cut in place (`sandbox/workspace/`, scripts
   tested without Docker; the image is **not yet built or run** — do that before
   depending on it).
2. `WorkspaceRuntime` interface + Docker driver + `workspaces` table + the REST
   endpoints above, with tests against a fake runtime.
3. WebSocket attach endpoint and ticket store.
4. `fab`: WebSocket transport for the agent pane, workspace state in the
   sidebar, files strip.
5. Token refresh for long-lived workspaces: make opencode config and
   `packages/agent-plugin` read the persona token from a file (re-read per
   request) and add a refresh writer in the workspace; today both read
   `FABAGENT_TOKEN` from the environment once at start.
