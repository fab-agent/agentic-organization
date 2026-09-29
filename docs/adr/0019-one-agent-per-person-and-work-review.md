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
4. **Route.** Risk ≥ threshold → inbox / alert (ADR-0013). Fit ratings are
   written to a review table and shown by the visibility rule below; repeated low
   scores on a criterion become **training-need** signals.

Scores and tags are side tables keyed to audit sequence numbers; **the audit
chain is never modified.** Scoring is sampled and uses a cheap model through the
gateway (ADR-0004); events are framed as data to classify, never as instructions.

**What is rated, concretely ("fit").** A criterion is a typed question tied to
something the company wrote down, answered per run/session with a probability and
a one-line reason:

| Source | Example criterion |
|---|---|
| Company goals / values | "Did this work advance goal G2 (grow recurring revenue)?" · "Is it consistent with value V (customer first)?" |
| Department goals / division of work | "Is this within the department's remit?" |
| Policies | "Was customer data handled as policy P-KVKK requires?" |

Alongside it, **hard signals** that need no model judgement: how often a request
was refused by a policy, how often approval was needed, how often the person
corrected the agent's output. Together they answer "where does this person or
unit need training or clearer rules?" — a KPI for training need, not a
disciplinary score.

**Who sees what (org hierarchy, `Personnel.manager_id` / `Department.parent_id`):**

| Viewer | Sees |
|---|---|
| The person | Their own ratings, reasons and signals, in full |
| Their direct manager | Per-person ratings and signals for their reports |
| The manager above | Per-team / section aggregates only |
| The level above that | Per-department aggregates only |

Transparency rules: a person always sees exactly what their manager sees about
them (no hidden ratings); they can annotate or contest a rating and the note
travels with it; the rubric is visible to everyone it is applied to; ratings
assess work against company criteria, never keystrokes, time-on-task or
screenshots; small groups are not shown as aggregates (a minimum group size
avoids identifying one person); per-company opt-in, purpose and retention set
before enabling (KVKK / GDPR); off by default.

### 7. The super tool

The product is the terminal workspace with that one agent and the company's
toolset behind it: documents, spreadsheets, presentations, ERP and other company
systems through MCP via the gateway, all under policy and audit. Its value to
the organisation is that the same tool serves every department *and* every run
is logged, tagged and rated for fit.

### 8. The person's local workspace folder

The person's area on their own computer is a **local folder** (for example on the
Desktop) that `fab` keeps in step with the server-side workspace (ADR-0018):

- Anything the agent produces — presentations, spreadsheets, an ERP report
  summary — appears here, from `/workspace/out`.
- The agent writes a **session summary** as a Markdown file here at the end of a
  session (`summaries/YYYY-MM-DD-<topic>.md`), so the person can follow their own
  work; the same files feed the daily review (ADR-0017 §4).
- Files the person drops into the folder's `in/` go up to the workspace.
- Outputs are one-way (server → laptop) and versioned by name (`report-v2.xlsx`);
  `fab` never overwrites a file the person has edited locally — on conflict it
  keeps both.
- `fab` is meant to be the first thing opened when work arrives (optional start at
  login).

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

## Decisions taken on the open questions

1. **Super tool:** confirmed — the workspace + one agent + the company toolset,
   with a synced local folder (§8) as the person's area on their computer.
2. **"Fit" is defined** as in §6: typed criteria from company goals and values,
   department goals and policies, plus hard signals; used as a training-need KPI.
3. **Visibility:** hierarchical as in §6 — person, then per-person for the direct
   manager, then team aggregates, then department aggregates.
4. **Subagent limits: follow opencode, and enforce what it does not.** opencode
   (SDK types v1.18.33) has per-agent `maxSteps` (iterations before it is forced
   to answer in text), `mode: "subagent"`, and per-agent `permission` / `tools` /
   `model`. It has **no** depth, concurrency or token-budget setting, so:
   `maxSteps` is set in the managed config; the token budget is the gateway's
   per-persona quota (ADR-0004), with derived run tokens carrying a sub-quota;
   depth and concurrency are enforced in `packages/agent-plugin`'s
   `tool.execute.before` hook (which can already block a call) by counting the
   subagent-launching tool's events — **to be verified against opencode 1.18.26
   before building**. Starting values to tune, not decided: depth 2, concurrency 3,
   `maxSteps` 40.

## Open questions

1. **Retention** of review rows and summaries (proposal: 12 months, per-company
   configurable) and who may export them.
2. **Authoring criteria:** how goals, values and policies become typed
   questions (draft by an LLM, approved through a change request — ADR-0017).
3. **Hard-signal list** and the minimum group size for aggregates.
4. **Legal review:** employee-related scoring should be reviewed by counsel
   (KVKK / GDPR) before it is enabled at any customer.
5. **Local folder sync:** location default, conflict handling details, and
   behaviour on shared / managed laptops.

## Follow-ups

1. Backend: one agent persona per human, created with the workspace;
   `Personnel.job_description`; run tree ids (`run_id`, `parent_run_id`) on
   audit events; derived (narrowing-only) tokens per run.
2. Pipeline: filter + tag stage, fit-scoring job (extends `audit_severity`),
   side tables, rubric versioning from the policy repo.
3. `fab`: "My area" view, work-centred sidebar (sessions/runs), refusal messages
   that name the rule, "propose a change" action.
4. Person view of own ratings (see, contest, annotate) before any manager view;
   review table + hierarchical aggregation queries.
5. `fab`: local workspace folder sync (manifest-based) and session-summary files.
6. Subagent limits: `maxSteps` in managed config, run sub-quotas at the gateway,
   depth / concurrency check in the plugin.
