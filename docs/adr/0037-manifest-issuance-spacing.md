# ADR-0037: Spacing out manifest issuance per person

- **Status:** proposed
- **Date:** 2026-11-03
- **Deciders:** Fabrika / fab.engineering
- **Related:** ADR-0028 (`GET /me/workspace`), ADR-0035 (the same pattern for reports)

## Context

Every `GET /me/workspace` allocates a generation, signs a manifest and appends an event to the audit
chain. A signed-in member (or a buggy client in a loop) can therefore grow the audit chain and the
generation counter without bound, and bury real events. Reports were already limited (ADR-0035);
issuance was not.

## Decision

1. **One issuance per person per 10 seconds.** A second `GET /me/workspace` inside the window answers
   `429` with `Retry-After: 10` and `{"detail": {"error": "rate_limited", "reason": "try_again_later"}}`.
   The person is the one resolved from the session, so one person cannot use up another's window, and a
   second device of the same person shares the window (a person has one workspace).
2. **The check is the write.** The slot is taken by one conditional `UPDATE ... WHERE issued_at <=
   now - 10 s` on `workspaceissuestamp` (one row per company and person; the first INSERT is protected
   by the unique key). Requests that all saw an old row cannot all pass. The helper `claim_slot` is the
   one used by reports as well.
3. **Before anything else is done.** The slot is claimed before a generation is allocated, a manifest
   signed or an audit event written, so a refusal changes nothing but the stamp. Consequence: an attempt
   that then fails with `503 workspace_unavailable` has used its slot; that answer already carries
   `Retry-After: 30`, longer than the window, so a client that obeys it is never refused.
4. **Not limited:** `/me/workspace/files/{sha}` (a sync fetches one per file; it writes nothing) and
   `/crl`. The CRL endpoint produces no generation, signature or audit event; it may raise the stored
   CRL high-water mark when a newer list is published, which is a security checkpoint that must not be
   held back. Both need authentication.
5. **The CLI** shows a plain message for the refusal (`server_try_again_later`): no new workspace was
   installed, and it does not retry on its own. A newer revocation list fetched just before the refused
   request is still kept (revocation information is never thrown away).

## What this does not do

- It is not a global or per-IP limit and does not stop password guessing or request floods before
  authentication; that belongs to the reverse proxy.
- A member can still cause one audit event per 10 seconds, which is the intended ceiling.

## Verification

Server: second request refused with the exact body and header; no audit event, no generation allocated
on refusal; per-person (another person unaffected); works again after the window; 503 leaves a spaced
slot; files and CRL are not limited; migration columns match the model; a PostgreSQL test races eight
claims and requires exactly one winner. CLI: the refusal is a plain code and, with no new revocation list,
leaves the state file byte-identical.
