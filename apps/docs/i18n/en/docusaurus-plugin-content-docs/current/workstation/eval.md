---
sidebar_position: 10
---

# Evaluation and Failure Attribution

> ADR-0023 · `backend/services/run_diagnosis.py`, `backend/services/run_reader.py`, `backend/api/eval.py`

When an agent run goes badly the question is "which layer do I fix?": model, prompt, tool or policy. There is no separate evaluation store; the record is the [audit chain](/workstation/audit-chain). The diagnosis reads it.

## Working today: run diagnosis (stage 1)

The audit events of one run (`run_id`) are read together and produce **findings** per layer:

| Layer | Example finding |
|---|---|
| `model` | Provider error, empty output |
| `prompt` | Sections dropped by the token budget (sections the intent skipped on purpose are not a fault) |
| `tool` | Tool error, the same tool failing repeatedly |
| `policy` | A denied or ask decision and the matched rule |

The result is a **suspect layer**; when layers tie, none is chosen. These are **signals, not proof**: they say where to look.

Trust rules:

- Message and document text is never read; names are shown only if they look like a short identifier (key, email and UUID shapes are not shown). This is not anonymisation.
- Events from a workstation are stamped `origin: client` by the server. Client claims of server-observed facts (gateway, policy, context) are ignored and counted.
- Dry-run decisions do not score; a fail-closed decision is a separate configuration fault.
- Input is capped at 5000 events; if cut, the result says `truncated`. Malformed events are counted, not fatal.

## API

| Endpoint | What it does |
|---|---|
| `GET /eval/personas/{id}/runs` | Lists stored diagnoses |
| `GET /eval/personas/{id}/runs/{run}` | Returns one diagnosis |
| `GET /eval/personas/{id}/summary` | Success share (with interval) and suspect-layer counts |
| `POST /eval/personas/{id}/runs/{run}/diagnose` | Computes the diagnosis, or returns the stored one if it is under 10 s old |

Access: founder; company-wide executive and department head; a department-scoped executive for that department only; the responsible person; the agent owner. Unauthorised, unknown or malformed `run_id` all return the same `404` and nothing is written. Diagnoses are erased with the person.

## Not there yet

- **Judges:** the first slice works. Deterministic judges derived from the diagnosis (`answered`, `no_tool_error`, `no_policy_block`) and `GET /eval/personas/{id}/summary` (success share with a confidence interval; abstentions counted apart; suspect layers are hypotheses, not fault rates). A TypeSafe `Noul` text judge exists in code but is not wired to stored session text, and no criterion counts before calibration.
- **Viewer page:** a first version exists (**Evaluation**, department head and above): agent picker, success shares, runs table and findings. No timeline or trend charts yet.
- **Replay:** re-running with only one layer changed to confirm a suspicion; needs the probe environment, which does not exist.
- Guardrail and data layers emit no events, so they show as "no signal".
- Gateway failures (timeout, connection, unparseable reply, cut stream) and empty output / `length` finishes are recorded on the `gateway_call` event and become `model` findings; a client hang-up is shown but not scored.
- Client events written before the `origin` stamp cannot be told from server events.
