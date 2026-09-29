# ADR-0020: Prompt assembly with a token budget, and intent breakdown with Jev

- **Status:** proposed
- **Date:** 2026-09-29
- **Deciders:** Fabrika / fab.engineering
- **Related:** ADR-0004, ADR-0005, ADR-0010, ADR-0015, ADR-0017, ADR-0019

## Context and problem

Agents must know who they work for and what rules bind them (company mission,
values, goals; department goals; the person's job; policies), and later they will
carry MCP servers and many tools. If all of that is pasted into every prompt, cost
and latency grow with every feature and small models degrade. We want the smallest
prompt that still works.

What the code did before this ADR (`backend/`): the web-chat prompt held name,
title, role, department name and goals, **policy names only**, skill names, three
memory notes and retrieved knowledge. Company vision / mission / values / goals were
stored (`Company.metadata_json`) and served by the companies API but **never reached
any prompt**. Scheduled flows used a three-line prompt. Nothing measured where the
tokens went.

## Decision

### 1. Assemble the prompt from named, counted sections (built)

`services/context_assembly.py`: every part is a `Section` (name, tier, token
estimate); a token budget (`PROMPT_BUDGET_TOKENS`, default 2000 — a starting value)
is enforced by dropping optional sections in a fixed order (`knowledge`, `memory`,
`department`, `job`, `company`); required sections (`identity`, `rules`, `closing`)
are never dropped. Every real prompt logs its per-section breakdown (`prompt_assembled`
— names and sizes only, never text), so growth is visible.

- **Stable first, per-turn last** so providers' prompt caching can reuse the long
  identical prefix: identity, company, department, job, rules, skills, closing, then
  memory and retrieved knowledge. (This moves the closing line ahead of memory /
  knowledge compared with the old order.)
- **Company context** (mission, vision, values, top goals) now reaches the prompt,
  compacted with hard caps and no model call (≤ 5 goals, ≤ 8 values, clipped lines).
- **The person's job** (`Personnel.job_description`) reaches a *workspace agent's*
  prompt (ADR-0019), not other agents'.
- **Policies stay names** (capped at 20). Enforcement is at tool-call time
  (ADR-0005), so a short list in the prompt is guidance; leaving detail out costs
  helpfulness, never safety.
- Token counts are **estimates** (no tokenizer is installed): fine for comparing
  sections and spotting growth, not for billing.

### 2. Long-tail content by reference, on demand (not built)

Keep a small digest inline for what most turns need; fetch the rest with a tool
(`lookup_policy`, company knowledge search via ADR-0015's ranker) instead of
inlining it. Small models are poor at deciding when to look things up and each
lookup is an extra turn, so the inline digest stays. Tool and MCP **schemas** are the
largest likely source of bloat; deferring them (name + one line inline, schema on
demand) is the plan where the client supports it — not verified for opencode. A
gateway that prunes `tools[]` mid-conversation would break prompt caching and can
make a provider reject a turn that calls a tool no longer listed, so any pruning
happens only at session start.

### 3. Intent breakdown with TypeSafe Jev (client built, not wired)

`services/intent.py`. Jev answers typed questions (choice / score / noul) with
calibrated probabilities (`POST /v1/systemone`; the SDK `typesafe-sdk` sends
`{state, model, questions}` and returns `{answers, usage, model}` — pinned by a test
against TypeSafe's documented example). Our question set: task type, whether the
answer needs company knowledge, sensitivity, and — when the company has departments
— the domain (a choice built from the company's own departments).

The result narrows the prompt (`sections_to_skip`): small talk leaves out every
optional section; a low need for company knowledge leaves out retrieved knowledge.
The same record becomes tags for the work-review pipeline (ADR-0019 §6), so one call
serves both.

Constraints, all tested:

- **Never a security control.** An intent can only narrow what the prompt shows; it
  cannot add sections or widen what is allowed. Policies are enforced elsewhere.
- **Fail open and fast.** 1.5 s timeout (`INTENT_TIMEOUT_SECONDS`), **no retries**
  (the SDK default is a 10 s timeout and two retries — wrong for a pre-model step),
  and any failure returns "no intent", i.e. the complete prompt. Choice answers below
  0.6 confidence count as unknown.
- **Cost gate.** TypeSafe's example used 392 input tokens for a ~25-word message: the
  questions themselves cost a few hundred tokens. So the call only pays off for
  prompts large enough to save more than that (`INTENT_MIN_PROMPT_TOKENS`, default
  800 — a guess to replace with measurements). Send only the user's message (capped
  at 2000 characters), never the assembled context.
- **No text in logs.** Errors log the exception type only; the SDK's DEBUG logging of
  request bodies (which contains the message) is filtered out.
- **Opt-in per install.** Requests leave the premises: off unless
  `TYPESAFE_API_KEY` is set *and* AppConfig `intent.enabled` is true (ADR-0015 /
  ADR-0016). A local classifier fallback is not built; without Jev the answer is
  simply the complete prompt.

## Options considered

- **A — do nothing / add context inline.** Simplest; cost and latency grow with each
  feature, and nothing shows where tokens go. Rejected.
- **B — shrink by hand.** One-off trimming without a budget or report regresses as
  soon as someone adds a section. Rejected.
- **C — sections + budget + report now, references and intent classification on top
  (this ADR).** Measurement first, then reduction.
- **D — prune tools at the gateway per intent.** Attractive because the gateway sees
  every request, but breaks caching and tool-call continuity mid-conversation.
  Deferred; session-start pruning only.

## Consequences

- **Positive:** the prompt has a bounded, visible size; company context finally
  reaches agents; the stable prefix is cache-friendly; Jev's output is reusable as
  tags.
- **Negative / cost:** company context adds up to a few hundred tokens to every chat
  prompt that has metadata; the intent call is a paid external round trip and a
  privacy trade-off; token figures are estimates.
- **Accepted residual risk:** a wrong intent can omit context an answer needed. The
  mitigations are the confidence floor, fail-open defaults, and never skipping the
  required sections.

## Not done yet

- **Nothing calls the classifier.** `build_system_prompt` does not use
  `sections_to_skip`; wiring it (and skipping the retrieval itself when knowledge is
  not needed) waits for a trial against the real API.
- **The real API has not been called** (no key, no egress here): confidence
  semantics, latency and per-call cost are unmeasured. The `noul` answer has no
  `confidence` field in the example; we read its value as a probability of "true" —
  verify against TypeSafe's documentation.
- No lookup tools, no tool-schema deferral, no MCP token accounting, no digests
  generated from full policy text, no local classifier.
- The workspace (opencode) path does not use this assembly yet: it needs an endpoint
  that serves the assembled context to the plugin.

## Trial status

A trial harness exists — `backend/scripts/intent_trial.py`, with its own tests — but
**it has not been run against the real API**: the session's network policy blocked
`api.typesafe.ai` (and the OpenAI-compatible endpoint used for token calibration), so
nothing has been measured. Run it from a session that can reach the services:

```sh
cd backend
TYPESAFE_API_KEY=... python scripts/intent_trial.py --repeat 3
# token-estimate calibration against a real tokenizer (any OpenAI-compatible endpoint):
OPENAI_COMPAT_BASE_URL=... OPENAI_COMPAT_API_KEY=... OPENAI_COMPAT_MODEL=... \
  python scripts/intent_trial.py --calibrate
```

It sends 20 synthetic English and Turkish requests (no company data) and reports
latency (p50 / p95), the fixed input-token cost of the questions, how often a choice
is confident, chit-chat recognised, **real work wrongly trimmed as chit-chat** (the
harmful direction — should be 0 before this is wired in), and how the `noul`
probability separates "needs company knowledge" from "does not". Decisions to take
from the numbers: `INTENT_MIN_PROMPT_TOKENS`, the 0.6 confidence floor, the 0.25
knowledge threshold, and the estimator's divisor for Turkish.

## Follow-ups

1. Trial Jev against real requests: latency, cost per call, calibration of the
   thresholds; decide `INTENT_MIN_PROMPT_TOKENS` from data.
2. Wire the classifier into the chat path (behind `intent.enabled`), skip retrieval
   when knowledge is not needed, and store `Intent.tags()` for review.
3. `lookup_policy` / company-knowledge tools on the MCP server; then digests.
4. Serve the assembled context to the workspace agent (`/workstation/context`).
5. Measure real prompts from the `prompt_assembled` logs and tune the budget.
