# ADR-0023: Evaluation and failure attribution on the audit trail

- **Status:** proposed
- **Date:** 2026-10-17
- **Deciders:** Fabrika / fab.engineering
- **Related:** ADR-0005, ADR-0006, ADR-0013, ADR-0020, ADR-0021, ADR-0022

## Context and problem

When an agent run goes wrong we can see *that* it did (audit chain, severity scores)
but not *which layer to fix*: the model, the assembled prompt (system prompt,
memory, rules), a tool or its guidance, a policy rule, a guardrail, or the data it
was given. ADR-0022's learning loop needs exactly this answer, or it will propose
edits to the wrong layer. The audit trail already records, per run, the pieces
needed: `run_start`, `context_served` (prompt sections, tokens, what was dropped by
the budget), `gateway_call` (model, upstream status, tokens, latency),
`tool_event` (phase, decision, error) and `policy_decision` (effect, matched rule).
Nothing reads them together. We also have no success measure for a run.

The audit chain is the source of truth for *what happened* (metadata and evidence
references). It is not a replay dataset: previews are truncated, redacted copies of
task, expected output, fixtures and versions are not in it. Replay therefore needs
its own deletable, access-controlled artifact store with retention and erasure
(ADR-0022 decision 10); this ADR consumes that store and does not replace it.
What is missing is a reader (diagnosis), a judge (success), and a way to confirm a
suspected cause (replay).

## Options considered

- **A —** adopt an external tracing/eval product as the system of record.
- **B —** derive everything from the audit chain: a deterministic *diagnosis* per
  run, judges for success, replay for confirmation; a viewer on top later.
- **C —** only LLM-judge whole transcripts.

## Decision

**B**, in three stages, each useful alone.

1. **Run diagnosis (deterministic).** Group a run's audit events and emit
   *findings*, each tied to a layer (`model`, `prompt`, `tool`, `policy`),
   a kind, the evidence (chain key + seq) and a short detail. Examples: upstream
   error or empty output (model); sections dropped by the token budget (prompt);
   a tool error, or the same tool failing repeatedly (tool); a deny/ask decision
   and its matched rule (policy). The diagnosis ranks layers by finding weight and
   names a *suspect layer*, or none when layers tie. These are **signals, not
   proof**: they say where to look. Rules that keep it honest:
   - it never reads message or document text, and prints a name only if it looks
     like a short identifier (audit previews are bounded but **not** redacted, so
     they are not used at all);
   - the chain proves an event was not altered, not that it is true. Events
     ingested from a workstation are stamped `origin: client` by the server;
     client claims of server-observed facts (gateway, policy, context events) are
     ignored and counted, and client-reported tool errors are kept but never rank
     above server-observed failures;
   - a correct block is not a defect: dry-run decisions are notes that do not
     score, enforced denials score as a hint, fail-closed decisions are a separate
     configuration fault; sections the intent skipped on purpose are not a prompt
     fault; zero provider usage is a weak hint only;
   - the caller selects the events (one company, one verified persona, one run).
     Policy decisions carry no run id yet, so joining them to a run is a follow-up
     that must not trust a client session reference alone; until then ambiguity is
     shown, not guessed;
   - malformed or duplicate events are counted and skipped, never fatal; input is
     capped.
2. **Judges (success measure).** A run or task gets an outcome from, in order:
   deterministic checks (did the expected output exist, did a required tool run);
   TypeSafe models, which return probabilities rather than text. `Noul` answers
   yes/no questions ("did the answer cite a source?"), `Choice` picks one of several
   outcomes. They follow ADR-0021's pattern: criteria are calibrated against labelled
   examples before they count, unclear is bounded, and results carry counts rather
   than texts. An LLM judge is a fallback for open questions only. Reported measures:
   success rate with an interval, per-layer fault rate, and calibration of each judge.
3. **Replay (confirmation).** For a suspected layer, re-run the same redacted task
   with only that layer changed (prompt section restored, a tool description
   corrected, a policy rule relaxed in a sandbox) and compare outcomes. Only a
   confirmed flip upgrades a finding from *suspect* to *attributed*. This is the
   probe environment of ADR-0022 §5; stage 3 does not ship before it exists.

Layers are `model`, `prompt`, `tool`, `policy` today. Guardrails and data/context
problems do not emit events yet and show as *no signal*; adding their layers needs
their producers to emit them first. Per-layer fault rates are computed from
*attributed* (replay-confirmed) results only, never from stage-1 suspects. Replay is
a human-started, sandbox-only counterfactual: a flip never allows the learning loop
to propose policy or permission changes (ADR-0022 stays in force) and does not
override the security veto. Judge input is minimised and redacted like ADR-0021's,
with the cloud/local path chosen at installation, and human-review data inherits
ADR-0021's opt-in, shadow, contest and erasure rules.

Findings and judge results are stored beside the chain (like `AuditSeverity`), keyed
to `(chain_key, seq)` or run id, and never written into the chain. Access is per
company and role; a person sees diagnoses of their own runs only.

A viewer (admin page: runs table, per-run timeline with findings, layer breakdown
over time) is a later step and is built on these tables; an external viewer
(Langfuse or Phoenix) can read an export if we want one, but is not the record.

## Consequences

- **Positive:** the learning loop gets a targeted "which layer" input; problems are
  visible without a new data pipeline; judges are measurable.
- **Negative / cost:** stage 1 only sees what is audited. Policy decisions carry no
  run id today, so they are matched by session reference; a gap or an unaudited
  layer (for example a guardrail that does not emit events) shows as no signal, not
  as no fault.
- **Accepted residual risk:** a wrong suspect layer; mitigated by labelling stage 1
  output as a hypothesis and requiring replay before any change is attributed.
- **Follow-ups:** (0) gateway transport failures (timeout, parse error, cut stream) and `finish_reason`/`has_output` flags are not audited yet and need typed bounded events; (1) stage 1 service + tests (done); (2) persisted findings
  and a read API with object-level checks (done: `RunDiagnosis`, `/eval/personas/{id}/runs`,
  access follows the workstation persona rule, policy decisions now carry the verified run); (3) judge interface and the first
  TypeSafe criteria with calibration; (4) viewer page; (5) replay with ADR-0022 §5.
