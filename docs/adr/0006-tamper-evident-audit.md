# ADR-0006: Tamper-evident audit (hash-chained, one-way stream)

- **Status:** proposed
- **Date:** 2026-09-01
- **Related:** ADR-0003, ADR-0004, ADR-0005; block/buzz `crates/buzz-audit/`

## Context and problem

Today `AuditLog` is a plain table (`models.py:326`); rows can be modified/deleted
afterwards, and only a few routers write to it. Agent tool calls, gateway
traffic, and policy decisions are not logged. For the "logs are kept and cannot
be tampered with" claim:

- Records must be **tamper-evident** (deletion/modification must be detectable).
- The laptop must only be able to **append**; it cannot read or modify history.
- If the collector is unreachable, the agent must **stop** (it must not silently
  run without logging while offline).

## Decision (proposed)

- **`backend/services/audit_chain.py`:** every record contains `prev_hash`;
  `hash = H(prev_hash || canonical_json(record))`. The chain head is periodically
  signed / anchored somewhere external (git, S3 object-lock).
- **`AuditLog` is extended** or a new `AuditEvent` table: `seq`, `prev_hash`,
  `hash`, `actor_type` (`human` | `agent` | `system`), `actor_id`, `action`,
  `target`, `reason`, `payload_json`, `created_at`. The buzz pattern: agent and
  human actions are the **same record type**.
- **Laptop → server:** `POST /audit/ingest`, one-way; batched, at-least-once,
  client-side buffer. The token is persona-scoped (ADR-0007). There is no read
  endpoint on the laptop.
- **Fail-closed:** if `3pa` cannot reach the ingest endpoint for N seconds, it
  stops the opencode session (the same principle as ADR-0002).
- **What is logged:** gateway calls (ADR-0004), every `tool.execute.before/after`,
  every policy decision (ADR-0005), sandbox start/stop, `permission.asked`,
  A2A/ChangeRequest approvals.
- **Verification:** an `audit verify` command checks the chain end to end;
  `e2e-nightly.yml` asserts it.

## Implementation status (2026-09-01)

- `append()` / `record()` (chain + legacy `AuditLog` mirror) / `verify()` /
  `ingest_batch()` shipped in `services/audit_chain.py`; `AuditEvent` model +
  migration `b7c1e0f4a2d9`. Endpoints `POST /audit/ingest`, `GET
  /audit/chain/verify`. Gateway calls, policy decisions, and tool events all
  route through `record()`.
- Current version: **single global chain**, in-process write lock only, SQLite.

## Decided direction

- **Per-tenant chain** — **done.** `AuditEvent` is keyed `(chain_key, seq)`;
  `chain_key` is the company id or `__global__`. The hash covers `chain_key`, so
  rows cannot be moved between chains. `append()` takes a PostgreSQL
  transaction-scoped advisory lock keyed by the chain (no-op on SQLite, where the
  in-process `threading.Lock` + the DB's own write serialisation cover the
  single-process case). The full cross-process guarantee lands with the Postgres
  move.
- **Severity triage** on top of the chain: see ADR-0013 (an LLM scores recent
  events via the gateway; high risk → inbox / Telegram).
- **External anchoring (2026-09-03):** `services/audit_anchor.py` — an hourly
  job records every chain's `(seq, head_hash)` to an append-only local log
  (`data/audit_anchors.jsonl`) and, when `backup_bucket` is set, PUTs the log to
  S3 (`ObjectLockMode=COMPLIANCE` for `audit_anchor_lock_days` days, falling back
  to an unlocked PUT if the bucket has no Object Lock). `check_anchors()` flags a
  chain whose live `seq` is **below** the last anchored seq (truncation) or
  whose head at the anchored seq **changed** (rewrite) — neither of which
  `verify()` can see. `GET`/`POST /audit/chain/anchors` (manager).

## Open questions

- Retention period and PII redaction (raw prompt/response — an ADR-0004 open
  question).
- A cross-process lock (Redis) for a **non-Postgres** multi-worker deployment —
  on Postgres the transaction advisory lock already covers it.
- Anchoring to the org git repo or a public timestamp notary in addition to S3.

## Consequences

- **Positive:** A deleted/modified record is detectable. A strong compliance
  narrative.
- **Negative / cost:** Chain writes are sequential — concurrency and performance
  need care. Fail-closed behaviour blocks the offline developer (deliberate, but
  friction).
