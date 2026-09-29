# ADR-0021: The fit rubric — how company goals, values and policies become typed questions

- **Status:** proposed
- **Date:** 2026-09-29
- **Deciders:** Fabrika / fab.engineering
- **Related:** ADR-0013, ADR-0015, ADR-0017, ADR-0019 (§6, open question 2), ADR-0020

## Context and problem

ADR-0019 §6 says work is rated for *fit* against the company's own goals, values
and policies, as typed questions with a probability, and that the rubric lives in
the policy repo. It left open how those questions are **authored, scoped, versioned,
validated and turned into something a person or manager sees**. Getting this wrong
is the main way work review becomes unfair: a vague question, a question about the
person instead of the work, or a rubric nobody outside management has read.

This ADR fixes the design. Nothing here is built yet (see *Follow-ups*); the numbers
marked *proposal* are starting values to calibrate, not measured results.

## Decision

### 1. A criterion is one yes/no question about a piece of work

A **criterion** asks about a run or session summary, never about the person, and
has exactly one question with a stated good answer:

| Field | Meaning |
|---|---|
| `id` | Stable id, e.g. `G2-recurring-revenue`. Never reused. |
| `question` | One closed question about *the work*: "Does this work advance recurring revenue?" One idea only; no "and/or". |
| `good_answer` | `yes` or `no`. Lets a policy concern read naturally ("Does the reply expose customer data outside its purpose?" → good answer `no`). |
| `source` | What the company wrote that this comes from: `{kind: goal\|value\|dept_scope\|policy, ref, quote}`. The `quote` is the exact source text. **A criterion without a source quote is invalid.** |
| `scope` | Company-wide, or department ids it applies to. |
| `applies_when` | Optional filter on the tags ADR-0019 already stores — `tasks`, `sensitivities`, `domains` (the intent tags of ADR-0020). A missing tag means not applicable. If it does not match, the work is **not applicable** and is not rated. |
| `thresholds` | `{met: 0.7, not_met: 0.3}` — *proposal*, per criterion. |
| `status` | `draft` → `shadow` → `live` (§5), later `retired`. |

Example (`rubric/rubric.yaml` in the policy repo):

```yaml
version: 1
criteria:
  - id: G2-recurring-revenue
    question: Does this work advance recurring revenue?
    good_answer: "yes"
    source: {kind: goal, ref: company.goals.2, quote: "Grow recurring revenue 20% in 2026"}
    scope: {departments: [sales, customer-success]}
    applies_when: {domains: [sales, renewals]}
    thresholds: {met: 0.7, not_met: 0.3}
    status: live
  - id: P-KVKK-purpose
    question: Does the output expose personal customer data beyond what the task needs?
    good_answer: "no"
    source: {kind: policy, ref: policy.kvkk, quote: "Personal data is used only for the stated purpose"}
    scope: {company: true}
    applies_when: {sensitivities: [personal]}
    status: shadow
```

### 2. What a rating is — and is not

For one run/session summary and each applicable criterion, the scoring model
returns a probability of "yes" (TypeSafe Jev `Noul`, ADR-0015/0020). Jev answers are
probabilities, not text, so **a rating carries no free-text reason** in this design —
which also keeps personal data out of stored rows; the reader sees the criterion and
the verdict. (An earlier draft of this ADR promised a one-line reason.) The
probability maps to a **verdict**: `met`, `not_met`, or `unclear` (between the
thresholds, or the model failed / abstained). `unclear` is a first-class result
and is never rounded to a side.

- **There is no per-person score and no overall grade.** Views show counts per
  criterion (met / not met / unclear / not applicable) and the criteria themselves.
  Averaging unlike questions into one number would hide exactly what the person needs
  to see.
- The scoring input is the **filtered, redacted** summary (ADR-0019 §6 step 1), not
  raw content or keystrokes.
- Scoring is **sampled** (*proposal*: 20 % of runs, all runs that touched a
  personal-data class) and uses a cheap model through the gateway (ADR-0004).
- Ratings are side rows keyed to audit sequence numbers; the chain is never touched.

### 3. Authoring: draft by model, decide by people, visible to all

1. **Draft.** The ADR-0017 import already reads goals, values and policies. A
   drafting pass proposes criteria from them, each carrying its source quote. It
   never proposes a criterion about a person's traits, and the linter below rejects
   any that do.
2. **Lint (automatic, blocking).** Reject: no source quote; a quote that is not in
   the cited source; more than one question; question naming a person or trait;
   topics ADR-0019 excludes (keystrokes, time on task, attendance, screenshots) or
   protected characteristics; a criterion for `personal`-sensitivity work whose
   source is not a policy. Budget caps: ≤ 12 live criteria
   per department, ≤ 30 company-wide (*proposal*) — each adds scoring cost and
   reading load.
3. **Decide.** The whole rubric change is **one change request** (ADR-0017's
   two-stage flow: department head, then admin) and lands in Git with author and
   approvers. The model drafts; people own the wording.
4. **Publish.** Everyone a criterion applies to can read it in `fab`
   (a rubric view beside "My review"). A criterion that is not readable by the
   people it is applied to cannot go `live`.

### 4. Versioning

A criterion's identity for comparison is `(id, hash of question + good_answer +
thresholds)`. Every rating stores the rubric commit, criterion id and hash. Editing
the wording creates a new version; **old ratings keep the old version and are not
silently re-rated**, and aggregates never mix versions. Retiring a criterion stops
new ratings; old rows follow normal retention.

### 5. Nothing goes live untested

`draft` → `shadow` → `live`:

- **Calibrate.** The author labels a small sample per criterion (*proposal*: 20
  summaries). The criterion may leave `draft` only if the model's verdicts agree with
  the labels at a bar the company sets (*proposal*: ≥ 85 % on decided cases, and
  `unclear` on ≤ 30 %). Same method as the ADR-0020 trial: measure, don't assume.
- **Shadow** (*proposal*: 14 days): ratings are computed and shown **only to the
  person concerned**. No manager view, no aggregate, no training-need signal. It
  shows what the rubric would say before it can affect anyone.
- **Live** requires an explicit approval recorded in the same change-request trail.

### 6. Where the result goes

- **Person:** their ratings in full, in "My review", before any
  manager can see anything (ADR-0019 person-first rule).
- **Contest.** A person can contest a rating with a note. A contested rating is
  marked, **excluded from manager per-person views' summaries, all aggregates and
  training-need signals** until the department head (not the direct manager)
  resolves it; the note travels with it.
- **Direct manager / above:** same hierarchy and minimum group size as the hard
  signals; aggregates only above the direct manager.
- **Training need is read at the unit first.** If many people in a unit are
  `not_met` on one criterion, the finding is "this rule or its training is unclear"
  and goes to the rubric owner, before anyone is looked at individually. A
  per-person training-need signal needs both a minimum number of rated items
  (*proposal*: 10 in 30 days) and a not-met share above a company-set bar, and is
  shown to the person first.
- **Never an automated decision.** Ratings are not to be the sole basis of any
  employment decision (KVKK / GDPR profiling limits); the acknowledgement screen
  and the rubric view say so.

### 7. Storage (proposal)

`workrating(id, company_id, personnel_id, day, run_id, criterion_id, criterion_hash,
rubric_version, criterion_status, verdict, probability, model, contest_note,
contested_at, resolved_at, created_at)`, unique per (person, run, criterion, hash).
The rubric version is a hash of the stored rubric text until the policy repo is wired;
the audit sequence range is dropped until a summary source exists. Same retention window and
erasure-with-the-person as the other review rows; covered by the existing daily
purge. Off by default with the rest of work review.

## Consequences

- **Positive:** every criterion traces to text the company wrote; people can read
  and contest what is applied to them; a bad rubric is caught in calibration and
  shadow before it touches anyone; unit-level reading points at unclear rules, not
  at people first.
- **Negative / cost:** an authoring workflow, calibration labelling effort, one
  scoring call per applicable criterion per sampled run (~500 input tokens each at
  the ADR-0020 measurement; batching several criteria into one call is untested),
  and shadow time before value shows. Model ratings can still be wrong; the
  `unclear` verdict, contest path and no-overall-score rule limit, not remove, that.
- **Accepted residual risk:** a company can still write a bad rubric that passes
  the linter (e.g. a proxy for a protected trait). The linter is a floor; counsel
  review (ADR-0019 open question 4) stays required before enabling at any customer.

## Follow-ups

1. ~~Rubric file format + linter~~ — done: `services/rubric.py` (parse, lint, hash, verdict, applicability; refs are positional: `company.goals.2`, `department.<slug>.goals.1`, `policy.<slug>`). Not yet wired to the policy repo or an API.
2. Drafting pass added to the ADR-0017 import; rubric change goes through the
   existing change-request flow.
3. ~~`work_rating` table + scoring job~~ — first slice done (see *Implementation
   status*); still to do: the summary source, the redaction stage, and running it
   from the scheduler.
4. Calibration tool (`labelled sample → agreement report`), `shadow` gating.
5. `fab`: rubric view, ratings in "My review", contest action.
6. Measure the thresholds, sample rate and batching on real summaries; replace the
   *proposal* numbers.

## Implementation status (2026-09-29)

Built: `services/rubric.py` (format, linter, hash, verdict, applicability) and
`services/rating.py` + the `WorkRating` table (migration `e7b3d9a25c48`): the rubric
stored behind the linter, a separate per-company switch for rating (off by default, and
only on top of work review), deterministic sampling (every personal-data run is rated),
one Jev call per run with one `Noul` question per applicable criterion, idempotent rows
keyed by criterion hash, fail-open, and retention / erasure covering the new rows.
Tested with a faked scorer and a mocked Jev transport (no network here).

Since then (same day): `services/redact.py`, the filter stage, applied inside `rate_run`
so no caller can skip it, and `rate_recent_sessions`, an hourly job that rates the LLM
summaries of recently closed agent sessions (`AgentMemory`), taking the tags from the
session's `intent_classified` audit event and the accountable person from the agent's
`responsible_id`. It does nothing without a scoring key or for a company that has not
switched rating on.

Then the person-first API (`/work-review`): `GET /me` now carries the person's fit
ratings — per day and as counts per criterion version, with the question text when the
company's current rubric still has that exact version. The person sees everything,
including `shadow` ratings and their own contested ones; the direct manager's per-person
view (and `person_view`'s default) shows only `live`, uncontested ratings, so the person
sees *more* than the manager, never less. `POST /me/ratings/{id}/contest` (note ≤ 1000
characters) hides a rating from everyone else until it is resolved; `DELETE` withdraws
the contest; `POST /ratings/{id}/resolve` closes it and is limited to a department head /
executive / founder whose scope covers the person — never the person or their direct
manager. Every contest, withdrawal and resolution is audited without the note. Rating has
its own company switch (`PUT /settings {"rating_enabled": true}`), which needs work review
on and the same acknowledgement, and stops when work review is switched off.

Then the aggregates: team (`/teams`) and department (`/departments`) results now carry
fit ratings as counts per criterion version — from `live`, uncontested ratings only, never
`shadow` and never one under contest — and a criterion appears only if at least the group
floor (`WORK_REVIEW_MIN_GROUP`, default 3) of *different people* were rated on it, so a
criterion cannot single a person out even inside a group large enough to be shown. How many
rows were held back is reported (`ratings_hidden`); who is not. A suppressed small group
carries no ratings at all. Totals per group can still be differenced against other groups'
totals, as with the hard signals; the floor limits that, it does not remove it.

Then calibration and the gates (`services/calibration.py`, `scripts/calibrate_rubric.py`).
The author labels examples (`expected: met | not_met`, judged against the criterion's own
good answer); the scorer rates the same texts (redacted first); the report gives agreement
on the *decided* answers, the unclear share, per-class counts and per-example verdicts —
never the texts. It passes only with at least 20 examples, 5 of each class, ≥ 85 %
agreement and ≤ 30 % unclear (the ADR's proposals, parameters not facts); a scorer that
shrugs at everything, or a failing call, counts as unclear and cannot pass. The result is
recorded for the criterion's *exact wording* (id and hash), so rewording sends it back to
calibration. `rating.set_rubric` now refuses a rubric in which a `shadow` or `live`
criterion has no passing calibration, or a `live` one has not been rated in `shadow` for
14 days under that wording. Drafts and retired criteria are never gated.

**Not built, and why it matters:**

- **The filter recognises identifiers by shape only** (secrets, e-mail, URL, card, IBAN,
  national id, phone, IP). It does not recognise names, addresses or details written in
  prose, so it is a floor: the summary still leaves the premises with Jev, and counsel
  review stays required. Long digit runs that fail their checksum may still be redacted as
  phone-shaped (the safe side).
- Only sessions with an LLM summary are rated; a session too short to be summarised
  (fewer than two messages) or whose summary failed is never rated.
- There is no
  training-need signal or rubric view. Calibration runs from the command line only
  (there is no API or `fab` screen for it), it has been exercised against a faked scorer,
  not the live Jev API, and the 85 % / 30 % / 20 / 14-day numbers are unmeasured. `fab`'s "My review" shows the
  person's ratings and lets them contest and withdraw (unit tests, plus a pty end-to-end
  run against the real backend); there is no screen for the person who resolves. The
  shadow period is a status of the criterion; nothing yet
  promotes a criterion from `shadow` to `live` after calibration (it is edited in the
  rubric file).
- The rubric lives in an `AppConfig` row, not in the policy repo behind a change
  request; the 20 % sample rate, thresholds and caps are unmeasured proposals.
- The Jev call with several `Noul` questions was exercised only against the documented
  wire format, not the live API.
