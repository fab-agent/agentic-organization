# ADR-0019: Task-scoped agent personas, created and routed automatically

- **Status:** proposed
- **Date:** 2026-09-29
- **Deciders:** Fabrika / fab.engineering
- **Related:** ADR-0005, ADR-0007, ADR-0010, ADR-0014, ADR-0016, ADR-0017, ADR-0018

## Context and problem

Today an agent is something a person sets up by hand: pick a persona, attach
skills and policies, then remember to use it. In a terminal workspace for every
department (ADR-0014) that is too much ceremony for a finance, HR or sales
person. The intended experience is the opposite:

> A salesperson asks for "the last 6 months of sales, compared with the last 3
> years". An agent appears that does that job. Over a few questions and
> answers the person teaches it how they want the analysis done, and it becomes
> their **Sales Analysis Agent** — narrow, ready, visible in the sidebar. Later:
> "turn what Sales Analysis found into a presentation" — a **Presentation
> Agent** takes over, using the analysis as input. The person never configured
> an agent; their way of working became a set of agents.

Everything an agent needs to know is already the person's own context: the
company (vision, mission, values, goals), the department (goals, division of
work), the person's own job, and the policies that bind them. What an agent
adds is only a **capability** for one kind of work.

## Decision

### 1. An agent is a task-scoped persona owned by a person

Each agent is a `Personnel` row of `type = agent` with an `AgentConfig` whose
existing `responsible_id` is the owning human. New fields on `AgentConfig`:
`origin` (`manual` | `auto`), `purpose` (one sentence, used for routing),
`pinned`, `use_count`, `last_used_at`, `retired_at`. A person has many agents;
one workspace (ADR-0018) hosts all of them as sessions.

### 2. Context is assembled in layers; guardrails cannot be overridden

Every agent session is built from, in this precedence order (lowest wins on
conflict):

1. Base rules (`sandbox/base-prompt.md`, ADR-0010).
2. **Policies** — company ∪ department ∪ the owner's own ∪ agent-specific.
   An agent can only *add* restrictions (`AgentPolicyLink`); it can never
   remove or relax what binds its owner. Policies are also enforced at tool-call
   time by the policy engine (ADR-0005), so no prompt or skill can talk past them.
3. Company context: vision, mission, values, goals (`Company.metadata_json`).
4. Department context: goals and division of work (`Department.goals`, description).
5. The person's own job: **new** — `Personnel.job_description` (free text; the
   installation kit, ADR-0016, can fill it from the org chart import).
6. The agent's `purpose` and its learned skills (section 4).

The invariant: **an agent's effective permissions are never greater than its
owner's.** The token minted for an agent session (ADR-0007) carries the owner's
scope, not more.

### 3. Routing: the right agent for each task, created when there is none

For every task a person types in the agent pane:

1. **Explicit wins.** `@name` or selecting an agent in the sidebar uses that agent.
2. Otherwise a **router** (a cheap model call through the gateway) receives the
   task plus the person's agents (`purpose`, top skills) and returns
   `{agent_id | "new", confidence, proposed_name, proposed_purpose}`.
3. **High confidence** → proceed, and say which agent and why in one line.
   **Low confidence** → ask one question ("Sales Analysis Agent, or a new agent?").
   **`new`** → create an agent from the proposed name/purpose with only the
   layered context above (no learned skills yet): it starts generic and narrows
   through use.
4. Every routing decision is audited (ADR-0006). Overriding it takes one key,
   and the override is stored as an example for the next routing.

This deliberately keeps agents **narrow**: different kinds of work get different
agents, so contexts do not bleed into each other.

### 4. Skills are learned from the person, visibly

As a person answers the agent's questions and corrects its output, the agent
proposes **skill updates** ("Sales Analysis: always compare to same period last
year; report in EUR; exclude cancelled orders").

- **Learn only from the person's own messages** — never from tool results,
  documents or web content (ADR-0010: those are data, not instructions).
  Otherwise a poisoned document could persist itself as a "skill".
- Skills live on the agent (existing `Skill` table; a markdown `content` field
  may need to be added — to be verified against the schema). They are versioned;
  each update is shown in a "what I learned" list, applied by default, and
  reverted with one key. Nothing about it needs configuring.
- Skills hold **instructions, never policy or credentials**, and sit below
  policies in precedence (section 2).
- **Promotion** of a personal skill to the department or company library
  (`CompanySkill`) goes through a change request (`/change-requests`), so a
  useful way of working can spread — with review.

### 5. Hand-off between agents passes artifacts, not context

"Make a presentation from what Sales Analysis found": the Presentation Agent
receives references to the other agent's outputs (files under `/workspace/out`)
and a short summary — **not** its conversation. Each side keeps its own narrow
context; the receiving agent's policies apply to the material. Transport can use
the existing agent-to-agent API (`/a2a`) — to be confirmed before building.

### 6. The sidebar shows the person's working set

A new **Agents** section in the `fab` sidebar (ADR-0014 layout): pinned agents
first, then by recent use, each with its state (working / blocked / idle) from
the platform and its open sessions beneath it. Auto-created agents are marked
so the person can rename, pin, merge or retire them.

## Options considered

- **A — manual agents (status quo).** Full control, too much ceremony for
  non-developers; most people would never set one up.
- **B — one general agent per person.** Simple, but context grows unbounded and
  mixes unrelated work; nothing gets narrower or better with use.
- **C — task-scoped agents, auto-created and routed (this ADR).** Matches how
  the work is divided; costs a router, a learning loop and an "agent sprawl"
  problem to manage.

## Consequences

- **Positive:** no agent configuration for the user; agents narrow with use;
  the person's recurring work becomes visible, reusable skills; department
  knowledge can be promoted through review.
- **Negative / cost:** routing mistakes send work to the wrong agent (mitigated
  by explicit override and a visible explanation); many auto agents can clutter —
  needs merge/retire and a cap; the org chart must not fill with auto agents
  (`origin = auto` is hidden from the org tree and from team counts; the `fab`
  sidebar's "Team" line must exclude them).
- **Accepted residual risk:** a wrong "learned" preference can subtly degrade an
  agent's output until reverted; the "what I learned" list and versioning are the
  mitigation, not prevention.

## Open questions

1. **Router thresholds:** what confidence auto-routes vs asks? Start
   conservative (ask often) and relax from override data.
2. **Approval for learned skills:** applied-by-default with revert is proposed;
   is that acceptable for every department, or do some (finance, legal) need
   explicit approval before a skill takes effect?
3. **Agent limits and retirement:** cap per person, and when an unused agent is
   archived automatically.
4. **Where `job_description` comes from** when the installation kit did not
   provide one (asked once at first use?).

## Follow-ups

1. Backend: `AgentConfig` fields, `Personnel.job_description`, context
   assembly service (layers 1–6), router endpoint, skill-proposal endpoint.
2. Filter `origin = auto` from `/org-tree` and team counts; update the `fab`
   sidebar accordingly.
3. `fab`: Agents section, `@agent` addressing, "what I learned" view.
4. Hand-off via `/a2a` (or a new artifact reference type), with tests.
