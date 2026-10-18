# ADR-0024: Workspace controller hardening follow-ups

- **Status:** accepted (partly implemented; the rest is listed as open)
- **Date:** 2026-10-18
- **Deciders:** Fabrika / fab.engineering
- **Related:** ADR-0018, ADR-0022

## Context

Codex review 3 of the workspace controller (2026-10-18) returned GO for an opt-in
release and listed risks it did not consider closed. This ADR records what we decide to
do about each, so release notes can state the limits truthfully.

## Decisions

1. **Helper orphans.** Helper containers are named `fab-ws-helper-<uuid>` and labelled.
   The controller removes its own helper in `finally`; additionally a background sweep
   (`WORKSPACE_REAP_SECONDS`, default 60) removes any helper older than the helper
   timeout plus 30 s. Workspaces are never touched by the sweep. *Implemented.*
2. **Download memory.** A download holds its transfer slot until the response has been
   sent, so buffered bytes are bounded by `WORKSPACE_MAX_TRANSFERS × 100 MB`, not by how
   slowly clients read. True streaming out of the helper stays open. *Implemented
   (bound); streaming open.*
3. **Purge race.** The volume check and the helper launch run under the per-workspace
   lock, so a purge cannot remove the volume in between and let `-v` create an empty one.
   Cost: a file transfer and a lifecycle call for the same workspace are serialised.
   *Implemented.*
4. **Lost replies.** Controller call timeout is 100 s (helper 90 s), below the backend
   client's 120 s, so a caller no longer gives up on work the controller is still doing.
   *Implemented.*
5. **Listing race.** `walk` re-checks type and size on the opened file descriptor
   (`fstat`) rather than the earlier name lookup. Manifest/download hash binding stays
   best-effort. *Implemented.*
6. **Lifecycle reconciliation.** Controller locks are per process, and backend DB
   transitions span controller calls without an operation id or generation. Decision:
   run **one controller process**; add per-workspace operation ids with compare-and-set
   on the DB row, plus a reconcile job that compares DB state with container state.
   *Open.*
7. **Infrastructure drift.** Label/image/internal-flag checks are not attestation. A
   periodic check of the proxy's full configuration and of extra members on workspace
   networks is planned. *Open.*

## Consequences

The release notes say: opt-in controller, one process, deployment-owned disk quotas and
Docker socket policy, items 6 and 7 open.
