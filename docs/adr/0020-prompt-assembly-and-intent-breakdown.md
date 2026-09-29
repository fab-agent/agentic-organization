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

### 3. Intent breakdown with TypeSafe Jev (built, wired behind `intent.enabled`)

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
  0.6 confidence count as unknown (kept: see Trial results).
- **Cost gate.** Measured: the questions cost ~520 input + ~120 output tokens per
  call, ~550 + ~140 with the company-department `domain` question. So the call only
  pays off for prompts large enough to save more than that
  (`INTENT_MIN_PROMPT_TOKENS`, default 1500 — about three times the fixed input
  cost; see Trial results for why even that is not a token win by itself). Send only
  the user's message (capped at 2000 characters, without attachments), never the
  assembled context.
- **First turn of a session only.** The chat prompt is rebuilt every turn, so
  narrowing it on a later turn would change the stable prefix (breaking prompt
  caching) and a bare "ok" / "tamam" that continues a task is classified as small
  talk (measured: 0.99 / 0.86). Classifying only the first message (the same turn
  that runs retrieval) avoids both, and costs one call per session.
- **Audited without text.** `intent_classified` in the audit chain: tags, skipped
  section names, model, input/output tokens and the prompt-size estimate — never the
  message. The prompt-assembly log adds `intent_skipped`.
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

- **Jev's price per call is unknown** (the trial measured tokens, not money), so
  whether the call is cheaper than the tokens it saves is not settled — see Trial
  results. The `noul` answer has no `confidence` field; we read its value as a
  probability of "true". The measurements are consistent with that (small talk
  0.04–0.12, "which policy covers …" 0.76–0.90) but TypeSafe's documentation was not
  checked.
- Only the first turn is classified; skipping optional sections on later turns is
  deliberately not done (see the constraint above).
- No lookup tools, no tool-schema deferral, no MCP token accounting, no digests
  generated from full policy text, no local classifier.
- The workspace (opencode) path does not use this assembly yet: it needs an endpoint
  that serves the assembled context to the plugin.

## Trial status

Run on 2026-09-29 against the real APIs (TypeSafe `jev-latest`; Qwen `qwen3.8-flash`
through an OpenAI-compatible endpoint for the tokenizer): `backend/scripts/intent_trial.py
--repeat 3 --calibrate` (20 synthetic English and Turkish requests × 3 = 60 calls, no
company data), plus two extra probes and one end-to-end run described below. To
repeat:

```sh
cd backend
TYPESAFE_API_KEY=... python scripts/intent_trial.py --repeat 3
# token-estimate calibration against a real tokenizer (any OpenAI-compatible endpoint):
OPENAI_COMPAT_BASE_URL=... OPENAI_COMPAT_API_KEY=... OPENAI_COMPAT_MODEL=... \
  python scripts/intent_trial.py --calibrate
```

Two defects in the harness itself surfaced only on the first real run and are fixed:
`--timeout` was read but never defined, and the calibration compared prompt tokens
that include the endpoint's fixed chat-template overhead (62 tokens on Qwen's default
template, 26 with thinking off) — it reported the estimate as *too low* (×1.12 en,
×1.22 tr) when it is in fact too high. The overhead is now measured with a one-token
message and subtracted, over five texts per language.

### Criteria for wiring the classifier in (set before seeing any numbers)

Proposals, to be confirmed or changed by the owner — written down first so the data
cannot quietly move the goalposts:

1. **Real work wrongly trimmed as chit-chat: 0** over at least 3 repeats of the
   whole set (both languages). Anything above 0 means more or better-worded
   criteria, not a lower bar.
2. **Calls slower than the 1.5 s production budget: rare** (say under 5 %).
   Otherwise raise `INTENT_TIMEOUT_SECONDS` knowingly or drop the feature — a
   classifier that mostly times out is pure overhead.
3. **`failed_open` from real errors (not from timeouts): near 0.** Investigate any
   `failure_reasons` other than timeouts before enabling.
4. **`INTENT_MIN_PROMPT_TOKENS` set from the measured fixed cost** (the `min` of
   `input_tokens`): only classify prompts several times larger than that.
5. **`noul` must separate** the "needs company knowledge" and "does not" means
   clearly before its 0.25 threshold is trusted; otherwise skip only on chit-chat.
6. Wire it behind `intent.enabled`, off by default, and log tags plus tokens spent
   (never text) so cost and effect stay visible.

### Trial results (2026-09-29)

**Measured** (60 calls, 20 cases × 3):

| | result |
|---|---|
| calls that failed open | 0 / 60 |
| latency | p50 0.24 s, p95 0.27 s, max 0.43 s; 0 / 60 slower than 1.5 s |
| tokens per call | 512–538 in (mean 520), 119–121 out; with the `domain` question 547–574 in, 140–142 out |
| `task` | 60 / 60 confident and correct; confidence 1.0 on clear requests, 0.86–0.99 on short small talk |
| `sensitivity` | 45 / 60 confident, 36 / 45 matching our labels; tags only, never used to trim |
| small talk recognised and trimmed | 12 / 12 |
| **real work wrongly trimmed as small talk** | **0 / 48** |
| `noul` when knowledge needed / not | mean 0.557 (range 0.24–0.87) / 0.195 |

Extra probe (14 mixed, short and confirmation messages, not part of the harness set):
"Good. Please proceed with the payment run." scored 0.19 and "Thanks! Now delete the
salary column…" 0.24 on `needs_company_knowledge`, so the old 0.25 threshold would
have dropped retrieval for real work; "yes, go ahead" / "evet, devam et" came back as
`action` at only 0.50 / 0.52, so the 0.6 floor correctly left them unknown; "ok" /
"tamam" came back as small talk (0.99 / 0.86); "What can you do?" as small talk
(0.86), which drops company and job context but keeps identity and skills.

**Against the criteria**

1. Real work trimmed as small talk: **0 / 48** over 3 repeats, both languages — met.
   (The set is synthetic and easy; the extra probe found nothing either, but mid-task
   confirmations are only safe because of the first-turn-only rule.)
2. Slower than 1.5 s: **0 / 60** (< 5 %) — met.
3. Failed open from real errors: **0** — met.
4. `INTENT_MIN_PROMPT_TOKENS` from the measured cost — **set to 1500** (from 800).
5. `noul` separates clearly — **not met**. The means differ, but individual cases
   overlap both ways: the Turkish "summarise this contract clause" (no knowledge
   needed) scored 0.66–0.70 while the English "send the overdue reminders" (needs the
   customer list) scored 0.24–0.26. Per the criterion the knowledge-only skip must be
   near-inert: the threshold went from 0.25 to **0.15**, below every real-work score
   seen (lowest 0.18), so in practice retrieval is skipped only where small talk is
   already trimmed. It is a margin, not a discriminator.
6. Wired behind `intent.enabled`, off by default, audited without text — done.

**Constants changed from the data**

- `INTENT_MIN_PROMPT_TOKENS` 800 → 1500.
- `LOW_KNOWLEDGE_NEED` 0.25 → 0.15.
- `MIN_CONFIDENCE` 0.6 **kept**: task answers were either ≥ 0.86 or ≈ 0.5 with
  nothing in between, so any value in that gap is equally supported and none of the
  measurements argues for moving it (raising it would only turn correct sensitivity
  tags at 0.54–0.66 into "unknown").
- `estimate_tokens` divisor: English 4.0 → 4.8, accented (Turkish) 3.0 → 3.3
  characters per token. Measured with Qwen's tokenizer over 10 texts: English
  4.92–5.25 (mean 5.06), Turkish 3.21–3.73 (mean 3.39). Set just below the measured
  minimum so the estimate still leans high. One tokenizer only — Claude's and GPT's
  differ.

### End-to-end (2026-09-29)

Real Jev + real Qwen through `build_system_prompt`, with `intent.enabled` set in
AppConfig and the audit chain on: a company with mission, vision, five values and five
goals, a department with goals, eight policy names, five skills and four (synthetic)
retrieved knowledge chunks. The same chat message answered once with the complete
prompt and once with the narrowed one; `prompt_tokens` is Qwen's, net of overhead.

| message | narrowed | prompt tokens full → narrowed |
|---|---|---|
| "Merhaba, günaydın!" | company, department, job, knowledge, memory | 557 → 102 |
| "Hi! Thanks, that was helpful." | same | 556 → 101 |
| "Sen kimsin, ne yapabilirsin?" | same | 558 → 103 |
| "What can you do?" | same | 553 → 98 |
| "Summarise this clause: Payment is due within 45 days…" | knowledge (`noul` 0.09) | 580 → 253 |
| "Which of our policies covers travel expenses above 500 euros?" | nothing (`noul` 0.84) | 562 → 562 |

The narrowed answers were correct and on topic in every case (the clause summary was
the same in both). One difference in the other direction: with the complete prompt the
reply to "Hi! Thanks, that was helpful." volunteered "since we've been working through
supplier reconciliation and payment plans…" — history invented from the retrieved
knowledge chunks (which were synthetic here); the narrowed reply did not.

**What this says about cost.** Each classification costs roughly 690 Jev tokens
(550 in, 140 out) and saved at most 455 Qwen tokens on this ~560-token prompt, on the
turns it helps at all. So on prompts this size the call is a net loss in tokens even
for small talk, which is what the gate is for; at 1500 it is a win only when a large
share of first turns are small talk or need no knowledge. Jev's price per token is
unknown here, so this is a comparison of counts, not of money. The steadier reasons to
enable it are the tags for the work-review pipeline and not injecting irrelevant
retrieved text into a greeting; the token saving becomes real once prompts carry MCP
and tool schemas (§2).


## Review notes (independent review of the wired-in version)

- **Fixed — the classifier call blocked the event loop.** `run_session` is an async
  generator serving every request in the worker, and the wiring called the classifier
  (a synchronous network round trip, up to its timeout) from `build_system_prompt`
  directly. It now runs in a worker thread (`asyncio.to_thread`, as the other
  blocking calls in that module already do). A test measures event-loop stalls while
  a slow prompt build runs (0.53 s without the fix). The old "first turn only" test
  matched a string in the source; it is replaced by tests that run `run_session`
  and check what the prompt builder receives on the first and later turns, and that
  attachment contents never reach the classifier.
- **This is not a token saver, and should not be sold as one.** As built it narrows
  only the first turn of a session, and the call costs ~690 tokens against a best
  case of ~455 saved at a ~560-token prompt (the trial's own figures). The gate at
  1500 estimated tokens keeps it away from small prompts but has not been shown to
  make it pay. What it does deliver: tags for the review pipeline, no retrieval (and
  no irrelevant retrieved chunks to build a story from — seen once, on synthetic
  data, with a greeting) for small talk, and one skipped retrieval round trip. Real
  token savings have to come from elsewhere: the cache-friendly stable prefix,
  tool / MCP schema deferral, lookup tools instead of inlined text.
- **`needs_company_knowledge` is asked but barely used.** Its separation criterion
  failed (means 0.557 vs 0.195, ranges overlapping), and after lowering the
  threshold to 0.15 it only fires on small talk that `task = chitchat` already
  catches. It still costs input tokens on every call and writes an unreliable tag.
  Proposal: drop the question (and the tag) unless a later trial shows it separates.
- **The token estimator is calibrated to one tokenizer** (Qwen). Other providers'
  tokenizers produce more tokens per English character, so budget and gate figures
  are optimistic for them; a per-provider factor would fix it.

## Follow-ups

1. ~~Trial Jev against real requests~~ — done 2026-09-29 (see Trial results). Repeat it
   on real (anonymised) first messages before turning `intent.enabled` on for a
   customer; the synthetic set is easy.
2. ~~Wire the classifier into the chat path~~ — done (first turn only, behind
   `intent.enabled`). Left: storing `Intent.tags()` on the work-review record (they
   are in the audit chain today, not yet consumed by the review pipeline).
3. Find out what a Jev call costs in money; only then is the token comparison above
   more than a comparison of counts.
4. `lookup_policy` / company-knowledge tools on the MCP server; then digests.
5. Serve the assembled context to the workspace agent (`/workstation/context`).
6. Measure real prompts from the `prompt_assembled` logs and tune the budget; check
   the estimator against Claude's and GPT's tokenizers, not only Qwen's.
