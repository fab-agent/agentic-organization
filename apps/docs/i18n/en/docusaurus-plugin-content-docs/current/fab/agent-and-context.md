---
sidebar_position: 3
---

# The Person's Agent and Prompt

## One visible agent per person (ADR-0019)

- Every human personnel record has exactly one agent persona (`type = agent`, a single `AgentConfig`, `responsible_id` = the human). It is created together with the workspace.
- The agent can start background tasks and subagents; subagents can call other subagents (depth, concurrency and budget limits by policy). They are **not personnel, they are runs**.
- The sidebar shows **work, not agents**: current and recent sessions/runs and their state.
- **Authority does not grow.** A subagent's authority is a subset of its parent's; each run receives a short-lived token derived from its parent's that can only narrow. The policy engine still decides at every tool call.
- Every audit event carries `person`, `session`, `run_id`, `parent_run_id` and a free-text `role`; even when the agent fans out, the run tree can be reconstructed.

## "My area"

A permanent view opened with one key: company context (vision, mission, values, goals), department goals, the person's role and job description (`Personnel.job_description`), the applicable policies in plain language and **what the agent will not do, and why**. If a request is refused or held for approval, the reply says which rule it is and offers "propose a change".

## Layered context

From low to high precedence: base rules → policies (company ∪ department ∪ person ∪ agent) → company → department → the person's job → what the agent has learned. Policies win; the agent can only add restrictions.

**Self-learning is visible and one-way:** learning is only from the person's own messages and corrections (never from tool results, documents or web content); what is learned is versioned and inspectable, and reverted with one key.

## Token-budgeted prompt (ADR-0020)

The prompt is assembled from named and counted sections (`Section`). The budget is `PROMPT_BUDGET_TOKENS` (default 2000, a starting value). If the budget is exceeded, optional sections drop in a fixed order: `knowledge`, `memory`, `department`, `job`, `company`. `identity`, `rules`, `closing` never drop.

- **Stable first, per-turn changing last:** so that the provider's prompt cache can use the long common prefix.
- Policies appear in the prompt only as **names** (at most 20). Real enforcement happens at tool-call time; leaving detail out costs helpfulness, not safety.
- Token counts are **estimates** (no tokenizer); they are for watching growth, not for billing.
- Every real prompt writes its section names and sizes to the log (`prompt_assembled`); the text is never written.

## Intent classification (TypeSafe Jev)

The user's **first message** of a session is classified by task type, whether company knowledge is needed, sensitivity and (if departments exist) domain. The result only **narrows** the prompt; for example a non-work greeting drops all optional sections. The same record becomes a tag for work review.

Constraints (all tested):

- **Never a security control.** Intent cannot add sections or widen authority.
- **Fast and fail-open.** 1.5 s timeout, no retry; any error means "no intent", that is the full prompt.
- **Cost gate.** About 520 input tokens per call. It runs only on large enough prompts (`INTENT_MIN_PROMPT_TOKENS`, default 1500).
- **Only the first turn of a session;** so that the prefix does not change and break the cache, and continuing messages such as "ok" are not treated as chat.
- **Without text in the audit:** the `intent_classified` event writes tags, skipped sections and token counts; never the message.
- **It leaves the company,** so it is off by default: `TYPESAFE_API_KEY` **and** AppConfig `intent.enabled` are needed together.

Measurement with real Jev (29 September 2026): 0/48 real work wrongly trimmed, p50 0.24 s. There is no local fallback classifier; without Jev the result is the full prompt.
