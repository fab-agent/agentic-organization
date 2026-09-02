# ADR-0013: LLM audit severity scoring

- **Status:** proposed
- **Date:** 2026-09-01
- **Deciders:** Fabrika / fab.engineering
- **Related:** ADR-0004, ADR-0006, ADR-0010

## Context and problem

The audit chain (ADR-0006) proves *integrity* — that no record was deleted or
altered. It does not tell an operator *which* of the thousands of recorded
actions is worth looking at. Pattern rules (ADR-0005) catch the known-bad; they
miss novel or context-dependent risk ("the backend agent just read every row of
the customers table and then made an outbound request").

The customer wants to plug in an OpenAI-compatible key and have the system
surface the risky events on its own.

## Options considered

- **A — thresholds / heuristics only.** Rule-based alerting on the gateway
  (token spike, off-allowlist host). Cheap, deterministic, but blind to intent.
- **B — a dedicated classifier** (Llama Guard, Lakera). Good for a fixed taxonomy
  of harms; another model to host; not tuned for "operational risk in this org".
- **C — LLM scoring over the audit stream.** A background job batches recent
  `AuditEvent`s, sends them (through the gateway, ADR-0004) to an
  OpenAI-compatible endpoint with a scoring rubric, and writes the verdict back.

## Decision (proposed)

**C, with A as a always-on cheap first pass.**

- **`services/audit_severity.py`** — an APScheduler job (the platform already
  runs one). Every N minutes it reads `AuditEvent`s since the last cursor,
  groups them by session / persona, and asks the model: *risk 1–5, one-line
  reason, category (data-exfil / destructive / policy-evasion / privilege / other),
  confidence*.
- **Traffic goes through the gateway** — same BYO endpoint, same audit, same
  quota. A dedicated cheap `small_model` setting.
- **Output:** a `severity`, `severity_reason`, `severity_category` written to a
  side table keyed by `AuditEvent.seq` (the chain itself stays immutable — we
  never write back into it).
- **Action:** score ≥ 4 → an `InboxMessage` to the persona's responsible human
  and a Telegram alert (both already exist). Score 5 + `enforce` mode → optional
  auto-revoke of the persona token (ties to ADR-0003 / ADR-0007).
- **Cost control:** only score events of interesting `action` types
  (`gateway_call` with large output, `tool_event` for `bash`/`write`/`webfetch`,
  any `policy_decision` with effect ≠ allow); sample the rest.
- **Prompt-injection safety:** audit payloads are untrusted content (ADR-0010) —
  the scoring prompt frames them as data to classify, never as instructions, and
  the job ignores any "score this 1" text inside an event.

## Implementation status (2026-09-02)

- `services/audit_severity.py` — an APScheduler job (`score_recent_events`, every
  10 min, no-op unless `severity.enabled=true`). Reads recent `AuditEvent`s of
  interesting kinds since a cursor, batches them, scores via an
  OpenAI-compatible model through the org's configured upstream, writes to a
  side table `AuditSeverity` (`(chain_key, seq)`; the chain is never touched).
- Score >= `severity.threshold` (default 4) → `InboxMessage` to the persona's
  responsible human. Telegram wiring is a follow-up.
- Prompt frames the events as data and tells the model to ignore embedded
  directives; the parser trusts only its own JSON shape (ADR-0010).
- Config: `severity.{enabled,model,threshold,batch}` in `AppConfig`.
- Migration `a4e6c8b02d17`.

## Open questions

- Batch size / cadence vs cost — tune against real volume.
- Per-company opt-in and its own model/endpoint, or platform-wide?
- Retention of the raw payloads the scorer sees (KVKK/GDPR — shared with ADR-0004).
- Should a high score feed back into the Policy Engine as a dynamic `untrusted`
  signal for that session?

## Consequences

- **Positive:** Turns an append-only log into a triage queue. Uses infrastructure
  that already exists (gateway, scheduler, inbox, Telegram).
- **Negative / cost:** Per-token cost on audit volume; latency between an action
  and its alert (minutes, not realtime); false positives create alert fatigue if
  the threshold is wrong.
