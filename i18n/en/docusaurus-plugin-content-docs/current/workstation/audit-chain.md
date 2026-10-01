---
sidebar_position: 4
---

# Tamper-evident Audit Chain

> ADR-0006 · `backend/services/audit_chain.py`, `backend/services/audit_anchor.py`

The [Audit Log](/guide/dashboard#audit-log) records every mutation but its rows can technically be edited. The execution layer adds a **hash-chained**, provable record for agent actions: if a row is deleted or changed, chain verification reveals it.

---

## Chain structure

A separate chain is kept for each tenant (company). The `AuditEvent` row:

| Field | Description |
|---|---|
| `chain_key` | The tenant chain key |
| `seq` | Sequence number within the chain (increasing from 0) |
| `action` | `gateway_call` · `policy_decision` · `tool_event` · `sandbox_start` … |
| `payload_json` | Event detail (treated as untrusted content) |
| `prev_hash` | The hash of the previous event |
| `hash` | `sha256(prev_hash + canonical(payload) + seq + …)` |

The first event's `prev_hash` is a fixed genesis value. Every new event is cryptographically linked to the previous one: insertion, deletion or modification breaks the chain.

---

## Write path

Gateway calls, policy decisions and tool events all pass through a single `record()` function. `record()`:

1. Appends a new `AuditEvent` to the chain (with an advisory lock in Postgres, so concurrent writes do not break the order).
2. For backward compatibility, also writes a mirror row to the old `AuditLog` table.

---

## Verification

| Endpoint | Description |
|---|---|
| `GET /audit/chain/verify` | Re-hashes a tenant's chain from the beginning to the end and checks integrity |
| `GET /workstation/audit/verify` | The persona-scoped version of the same (`3pa audit verify` calls this) |

`verify_all()` checks all tenant chains; an APScheduler job runs it periodically.

---

## External anchoring

Someone who takes over the server could rewrite both the chain and the verification. Against this, `services/audit_anchor.py` periodically writes the chain **heads** (chain_key, last seq, last hash) outside the platform:

| Target | How |
|---|---|
| Local `jsonl` | An append-only file, on a separate disk/directory |
| S3 Object Lock | A bucket in **COMPLIANCE** mode: the object cannot be deleted or changed, even by root, until the retention period expires |

`check_anchors()` compares the current chain with the last anchor; if the head has gone backwards or the hash does not match it reports **truncation / rewrite** detection.

| Endpoint | Description |
|---|---|
| `GET /audit/chain/anchors` | Lists the recorded anchors |
| `POST /audit/chain/anchors` | Take an anchor now (normally the scheduled job does it) |

Configuration is in `AppConfig`: anchor interval, S3 bucket/prefix/retention.

---

## Severity scoring

The audit chain proves *integrity*, not *importance*. Which events are worth looking at is determined by **LLM severity scoring** (ADR-0013, `services/audit_severity.py`): a job running every 10 minutes has a model classify interesting events (risk 1–5 + category + reason), and sends high-scoring ones to the responsible human as an `InboxMessage` and as an alert to the company's Telegram admin chat. The score is written not to the chain but to the `AuditSeverity` side table; the chain never changes. With `severity.autopolicy` on, if a company accumulates a threshold number of high-severity events within an hour, the policy mode is automatically moved to `enforce`.
