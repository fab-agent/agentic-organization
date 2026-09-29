# ADR-0019: One agent per person, subagents internal; the organisation layer is area, rules and review

- **Status:** proposed
- **Date:** 2026-09-29 (revised the same day; replaces the first draft "task-scoped agent personas")
- **Deciders:** Fabrika / fab.engineering
- **Related:** ADR-0005, ADR-0006, ADR-0007, ADR-0010, ADR-0013, ADR-0014, ADR-0016, ADR-0017, ADR-0018

## Context and problem

The first draft of this ADR made agents a visible, per-task thing: the platform
would auto-create a "Sales Analysis Agent", route work to it, and list it in the
sidebar. That copies the old mental model (many named agents the person manages)
into the terminal.

Modern agent tools do not work that way. A person hands work to *one* agent; that
agent spawns background tasks and sub-agents on its own, learns from how it is
used, and can call other agents. How many agents ran is an implementation detail.
What matters to the person is: **their area exists, the rules are visible, what
is not allowed is visible, and the agent is always within reach.**

What an organisation adds — and what no individual tool provides — is
**accountability**: every piece of work logged, filtered, tagged, and rated for
*fit with the company* (goals, values, policies), not just counted as telemetry.
The deliverable is one **super tool** for the whole organisation: the workspace
(ADR-0014) with one agent that can do the tool work, inside the company's rules.

## Decision

### 1. One visible agent per person; subagents are internal

- Each human `Personnel` gets exactly one agent persona (a `Personnel` row of
  `type = agent`, one `AgentConfig`, `responsible_id` = the human), created with
  the workspace (ADR-0018). Existing links keep working: `AgentPolicyLink`,
  gateway tokens, audit attribution.
- That agent may start background tasks and subagents, and subagents may call
  other subagents, within a depth / concurrency / budget limit set by policy.
  **They are not `Personnel`**; they are runs.
- The sidebar shows **work, not agents**: current and recent sessions/runs and
  their state (working / blocked / done), plus an optional "activity" detail view
  for the curious. No per-task agent list, no agent management screens.

### 2. What the person can always see: area, rules, limits

A permanent, one-key **"My area"** view: company context (vision, mission,
values, goals), department goals and division of work, the person's own role
and job description (new `Personnel.job_description`), the policies that apply
in plain language, and **what the agent will not do and why**. When a request is
refused or held for approval, the reply says which rule, links to it, and offers
"propose a change" (ADR-0017 §2).

### 3. Layered context, and no privilege growth

Context for every session is layered, lowest precedence first: base rules
(ADR-0010) → policies (company ∪ department ∪ own ∪ agent) → company → department
→ person's job → the agent's learned memory. Policies win; an agent can only add
restrictions. **A subagent's authority is a subset of its parent's, and the
root's is a subset of the person's**: each run receives a short-lived token whose
scope is derived from its parent's and can only narrow (ADR-0007). The policy
engine still decides at every tool call (ADR-0005).

### 4. Attribution: every event says who, in what run

Every audit event (ADR-0006) carries `person`, `session`, `run_id`,
`parent_run_id` and a free-text `role` label the agent gave the run ("sales
analysis"). This keeps the log meaningful when the agent fans out, and makes a
run tree reconstructable for review.

### 5. Self-learning stays visible and one-way

The agent keeps personal memory and skills that improve with use.

- **Learn only from the person's own messages and corrections** — never from
  tool results, documents or web content (ADR-0010: data, not instructions).
- Memory/skills are versioned and inspectable ("what I have learned"), with
  one-key revert. They hold instructions, never policy or credentials, and sit
  below policies in precedence.
- **Promotion** of a personal skill to the department or company library goes
  through a change request (ADR-0017), so a good way of working spreads with review.

### 6. The work-review pipeline (the organisational value)

Every run and session passes through one pipeline. It extends ADR-0013 (risk
scoring over the audit stream) and ADR-0017 (behaviour checks, daily review); it
is not a second system.

1. **Filter.** Classify and redact sensitive content before anything is stored or
   sent to a scoring model (data class: public / internal / personal / financial).
2. **Tag.** Attach structured tags: department, topic, customer / project,
   data class, action types (read / write / send / spend), tool used. Tags make
   work searchable and reportable.
3. **Rate fit.** Score each run/session against the company's own criteria —
   goals, values, applicable policies — as **typed questions with a probability**
   (e.g. "advances goal G2?", "consistent with value V?", "any policy P
   concern?"), not a free-form grade. The rubric is the company's policy repo
   (ADR-0017), so leadership defines "fit", and every score records which
   rubric version it used.
4. **Route.** Risk ≥ threshold → inbox / alert (ADR-0013). Fit trends → the
   person **first**, then their manager (ADR-0017 §4). Aggregates → department
   and company views.

Scores and tags are side tables keyed to audit sequence numbers; **the audit
chain is never modified.** Scoring is sampled and uses a cheap model through the
gateway (ADR-0004); events are framed as data to classify, never as instructions.

**Guardrails on the reviewing itself** (this is information about employees):
the person sees their own ratings and reasons first and can contest or annotate;
the rubric is visible to everyone it is applied to; ratings assess *work against
company criteria*, never keystrokes, time-on-task or screenshots; access
(person / manager / HR), purpose and retention are set per company before the
feature can be enabled (KVKK / GDPR); off by default.

### 7. The super tool

The product is the terminal workspace with that one agent and the company's
toolset behind it: documents, spreadsheets, presentations, ERP and other company
systems through MCP via the gateway, all under policy and audit. Its value to
the organisation is that the same tool serves every department *and* every run
is logged, tagged and rated for fit.

## Options considered

- **A — many visible task agents, auto-created and routed** (this ADR's first
  draft). Matches an older "org of named agents" model; costs a router, agent
  sprawl and org-chart pollution, and asks the person to care about something
  the tools already handle internally.
- **B — one agent per person, subagents internal, org layer = area + rules +
  review (chosen).** Matches how current agent tools behave; the person sees
  work, not machinery; the organisation gets accountability through the pipeline.
- **C — no per-person agent identity (a shared company agent).** Loses per-person
  scope and attribution. Rejected.

## Consequences

- **Positive:** simpler UX and data model (one agent per person); no routing
  problem; the organisation's control comes from area, rules, attribution and
  review, which are the parts it actually owns; builds on ADR-0013/0017.
- **Negative / cost:** one agent's context grows — needs subagents, compaction
  and memory to stay sharp; run trees need attribution work end to end; LLM
  rating can be wrong or biased (false "unfit" flags) and costs tokens (sampling,
  cheap model, contest path).
- **Accepted residual risk:** the review pipeline is employee-related personal
  data and can be misused as surveillance. The guardrails in §6 (person-first,
  visible rubric, work-not-activity, per-company opt-in, retention) are the
  mitigation; the operator's policy decides how far a given company goes.

## Open questions

1. **What exactly is the "super tool"?** §7 is our reading (the workspace + one
   agent + company toolset). Confirm, and list the first toolset (e.g. Office
   documents, PDF, ERP lookups).
2. **Who defines "fit"?** Rubric owner (leadership via the policy repo?) and how
   values and goals become typed questions.
3. **Who sees ratings** — person, manager, HR — and for how long are they kept?
4. **Subagent limits:** default depth / concurrency / token budget per run.
5. **Activity view:** how much of the run tree the person sees by default.

## Follow-ups

1. Backend: one agent persona per human, created with the workspace;
   `Personnel.job_description`; run tree ids (`run_id`, `parent_run_id`) on
   audit events; derived (narrowing-only) tokens per run.
2. Pipeline: filter + tag stage, fit-scoring job (extends `audit_severity`),
   side tables, rubric versioning from the policy repo.
3. `fab`: "My area" view, work-centred sidebar (sessions/runs), refusal messages
   that name the rule, "propose a change" action.
4. Person-first review UI (see, contest, annotate) before any manager view.
