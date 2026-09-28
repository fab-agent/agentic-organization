# ADR-0017: Company policies as versioned guardrails, and daily work review

- **Status:** proposed
- **Date:** 2026-09-28
- **Deciders:** Fabrika / fab.engineering
- **Related:** ADR-0005, ADR-0006, ADR-0013, ADR-0014, ADR-0015, ADR-0016

## Context and problem

Companies already have written policies (HR, finance, procurement, data
protection, brand). They should become the agents' guardrails without anyone
re-typing them, and they must evolve the way code does: a person who is unhappy
with an agent's behaviour proposes a change, management approves or rejects it,
and every version is kept.

Most of the machinery exists:

- `Policy` rows hold a Markdown body per company / department / agent scope.
- The policy engine (ADR-0005) already reads machine rules from fenced
  ` ```policy ` / ` ```yaml ` / ` ```json ` blocks inside that Markdown and
  enforces them (`off` / `dry_run` / `enforce`, fail-closed).
- Change requests already run `submitted → dept_head_approved → admin_approved →
  committed`, ending in a Git commit; `git_sync` mirrors policies to
  GitHub / GitLab / Gitea.

Missing: getting existing documents *into* that shape, letting people propose
changes from where they work, guarding behaviour that cannot be written as a
tool rule, and closing the loop with a daily review of each person's work.

## Decision

### 1. Import: documents → policy Markdown → Git

- Docling (ADR-0015) converts each policy document. An import job splits it into
  one `Policy` per section/topic with the source document, page and version
  recorded, scoped by the installer (company / department).
- An LLM pass **proposes** two things per policy, never applies them:
  - machine rules as a ` ```policy ` block (tool / args / effect), for anything
    enforceable at tool-call time (e.g. "payments above 50 000 TRY → ask");
  - **behaviour checks** — short yes/no statements for rules that are about
    content, not tools (e.g. "the reply shares a colleague's salary").
- The whole import lands as **one change request** — a reviewable diff — and is
  committed to the company's policy repo only after approval. Rules start in
  `dry_run` so their effect is visible in the audit log before `enforce`.

### 2. Changes come from the people who work with the agents

- In the TUI (ADR-0014) and the web UI, "I don't want the agent to do this" on a
  message or a run opens a change proposal: the agent drafts the Markdown / rule
  diff, the person edits and submits it.
- Submission creates a change request; department head and admin approve or
  reject (existing two-stage flow); approval commits to Git with the author and
  approvers in the commit, and the engine reloads the policy.
- The policy repo is the source of truth; the database is a cache rebuilt from
  it. Every rule decision in the audit log records the policy commit it used.

### 3. Two guardrail layers

- **Tool-call rules** — the existing policy engine, unchanged.
- **Behaviour checks** — evaluated on agent output before it is shown or sent,
  as typed boolean questions to Jev (ADR-0015), or a local classifier when the
  install keeps data on premises. A check above its threshold blocks or routes
  the output to `ask`, and is audited like a rule decision.

### 4. Daily review against goals

- At the end of the day, each person's workspace sessions are summarised
  (extending `memory_service`, which already summarises sessions).
- The summary is scored against the person's goals and their department's goals
  (`Department.goals`, plus a new per-person goals field) with typed Jev
  questions — per goal: progressed / not touched, with a probability — not a
  free-form grade.
- **The person sees their own review first**, can correct or annotate it, and
  it then goes to their manager. Reviews are about the work, not keystrokes: no
  activity tracking, no screenshots.

## Consequences

- **Positive:** Existing policies become guardrails with human review, full
  version history and a named approver for every change. People shape agent
  behaviour directly instead of filing tickets. Managers get a daily, goal-based
  view of what the agents and people achieved.
- **Negative / cost:** LLM-proposed rules need careful review; the import diff
  can be large for a big policy set. Behaviour checks add a model call per
  output (cheap with Jev, but not free).
- **Accepted residual risk:** Daily reviews are personal data about employees.
  Before enabling them an install must define purpose, retention and access, and
  inform employees (KVKK / GDPR). They are off by default and enabled per company.
- **Follow-ups:**
  1. Policy import job (Docling → per-section `Policy` + proposed rules/checks →
     one change request).
  2. Git as source of truth for policies (repo layout, reload on commit, commit
     id in audit entries).
  3. "Propose a change" action in TUI + web on a message / run.
  4. Behaviour-check evaluator (`Ranker`-style interface: Jev / local).
  5. Per-person goals + end-of-day summary + goal scoring, opt-in per company.
