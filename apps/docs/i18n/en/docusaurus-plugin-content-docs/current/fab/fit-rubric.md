---
sidebar_position: 5
---

# Fit Rubric and Rating

A piece of work's **fit** with the company's goals, values and policies is measured with typed yes/no questions and a probability (ADR-0021). Not a free-text note; a classifier (TypeSafe Jev `Noul`) returns a probability.

> **Status:** works and is tested, but has not been measured with the live Jev API and has not passed legal review. That is why it comes **off** per company.

## Criterion

A criterion is a single yes/no question **about the work**; never about a person or a trait.

| Field | Meaning |
|---|---|
| `id` | Permanent identity (`G2-recurring-revenue`), never reused |
| `question` | A closed question with one idea |
| `good_answer` | `yes` or `no` (policy questions may want "no") |
| `source` | `{kind, ref, quote}`: the **verbatim quote** of the source text the company wrote. A criterion without a quote is invalid |
| `scope` | Company-wide or departments |
| `applies_when` | A filter by task, sensitivity and domain tags; if there is no match the work is **not applicable** |
| `thresholds` | `{met: 0.7, not_met: 0.3}` (proposal) |
| `status` | `draft` → `shadow` → `live`, then `retired` |

## What a rating means

The probability is turned into a **verdict**: `met`, `not_met` or `unclear`. `unclear` is a first-class result and is never rounded to a side. **There is no per-person score and no overall grade;** the views show counts per criterion (met / not met / unclear / not applicable). Jev does not generate text, so there is no free-text reason on a rating row either (which also keeps personal data out of the rows).

Rating is **sampled** (proposal: 20% of runs; every run that touches the personal data class) and works on the filtered summary.

## Nothing goes live without being tested

1. **Calibration.** The author writes labeled examples per criterion. The agreement of the model's verdicts with the labels must be at least 85% (unclear at most 30%); at least 20 examples, 5 of each class. The result is recorded for the criterion's **exact wording**; rewriting sends it back to calibration.
2. **Shadow period** (proposal: 14 days). Ratings are computed but shown **only to the person concerned**; there is no manager view, no totals and no training signal.
3. **Live.** Explicit approval is needed.

`set_rubric` enforces these gates: a `shadow`/`live` criterion that has not passed calibration, or a `live` criterion that has not stayed 14 days in shadow, is rejected. Today the `shadow → live` transition is done by hand in the rubric file.

Calibration runs from the command line:

```bash
cd backend
TYPESAFE_API_KEY=... python scripts/calibrate_rubric.py \
  --company <id> --samples samples.yaml [--save]
```

The report gives the agreement rate, the unclear share, class counts and per-example verdicts; never the texts.

## Versioning

A criterion's identity is `(id, digest of question + good_answer + thresholds)`. Old ratings stay with the old version and are not silently re-rated; totals do not mix versions.

## Contesting

A person contests a rating with a note (≤ 1000 characters) (`c`). A contested rating drops out of the manager view, all totals and training signals. It is resolved by the **department head / executive / founder**; not by the person themself or their direct manager. Every contest, withdrawal and resolution is audited (without the note text).

## The training-need signal

It is read **at the unit** first: if many people in a unit are `not_met` on the same criterion, the finding becomes "this rule or its training is unclear" and goes to the rubric owner (department head, executive, founder). Only `live`, uncontested, decided ratings count (last 30 days); at least 10 ratings, a `not_met` share above the bar (proposal 50%), and the group floor (3) must be satisfied.

**A person's signal is visible only on their own screen.** If they wish, they share it with their direct manager (`t`, `s`, `y`); sharing is consent per criterion, not a copy of data, and can be withdrawn. The company must first turn on `sharing_enabled`; it is **off** until legal review is finished. Team leaders see only their own team's unit finding (counts only).

## Not there yet

- The rubric lives in an `AppConfig` row; it has not been moved to the policy repository and the change request flow.
- There is no rubric view, unit findings or contest-resolver screen in `fab` (the APIs are ready).
- Calibration has no API or screen, only the command line.
- All thresholds (85%, 30%, 20, 14 days, 20%, 10, 50%, 3) are **proposals, not measured.**
