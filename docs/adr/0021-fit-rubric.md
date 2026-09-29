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
returns a probability and a one-line reason (TypeSafe Jev, ADR-0015/0020). The
probability maps to a **verdict**: `met`, `not_met`, or `unclear` (between the
thresholds, or the model failed / abstained). `unclear` is a first-class result
and is never rounded to a side.

- **There is no per-person score and no overall grade.** Views show counts per
  criterion (met / not met / unclear / not applicable) and the reasons. Averaging
  unlike questions into one number would hide exactly what the person needs to see.
- The scoring input is the **filtered, redacted** summary (ADR-0019 §6 step 1), not
  raw content or keystrokes. The reason (≤ 200 characters) must not quote personal
  data; it is redacted with the same filter before storage.
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

- **Person:** their ratings and reasons in full, in "My review", before any
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

`work_rating(id, company_id, personnel_id, day, run_id, audit_seq_from,
audit_seq_to, criterion_id, criterion_hash, rubric_commit, verdict, probability,
reason, model, contested_at, resolved_at, created_at)`. Same retention window and
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
3. `work_rating` table + scoring job (sampled, gateway, redaction) reusing the Jev
   client from ADR-0020; verdict mapping and versioning.
4. Calibration tool (`labelled sample → agreement report`), `shadow` gating.
5. `fab`: rubric view, ratings in "My review", contest action.
6. Measure the thresholds, sample rate and batching on real summaries; replace the
   *proposal* numbers.
