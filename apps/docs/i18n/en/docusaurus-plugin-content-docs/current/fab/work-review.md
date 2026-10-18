---
sidebar_position: 4
---

# Work Review

Every run and session passes through a single pipeline (ADR-0019 §6). The pipeline extends the risk scoring in ADR-0013; it is not a second system. It is **off per company by default**; the founder turns it on.

## The pipeline

1. **Filter.** Sensitive content is classified and masked before being stored or sent to a scoring model.
2. **Tag.** Department, topic, data class, action types (read/write/send/spend), the tool used.
3. **Rate fit.** Against the company's own criteria (see [Fit rubric](/fab/fit-rubric)).
4. **Route.** If the risk threshold is exceeded, inbox/alert; repeated low results become a **training-need** signal.

Scores and tags are side tables tied to audit sequence numbers. **The audit chain is never modified.**

## What is collected, and what is never collected

Collected: run/session summaries (filtered), tags, counts of policy refusals and approvals, how many times the person corrected the agent's output.

**Never collected:** keystrokes, time spent on screen, attendance/absence, screenshots. When it is off, `fab` says "nothing about you is being collected".

## Who sees what

| Viewer | What they see |
|---|---|
| The person themself | Their own scores, signals, details: all of it |
| Direct manager | Per-person results for their reports (only in-force, uncontested) |
| The manager above | Only team/section totals |
| Higher | Only department totals |

Rules: the person sees **more** than what the manager sees, never less; there are no hidden scores. Small groups are not shown as totals (minimum group size, `WORK_REVIEW_MIN_GROUP`, default 3). The person can add and delete their own notes. **Scores can never be the sole basis of any employment decision** (KVKK/GDPR profiling limits).

## In `fab`: "My work review" (`v`)

Totals, days, what is and is not collected, who sees it, and the person's own notes. For ratings, `c` contests and `u` withdraws. For the training signal, `t` selects, `s` asks about sharing, `y` confirms, `s` again withdraws.

## Scheduled jobs

| Job | Frequency |
|---|---|
| `work_review_rollup` | hourly |
| `work_review_purge` | daily |
| `work_rating` | hourly |

The retention period is **365 days** by default; when a person is deleted their rows are deleted too.

## Known limit: filtering looks only at shape

The filter masks emails, URLs, cards, IBANs, Turkish national IDs, phones, IPs and secret keys. **It does not recognize names, addresses or details written in plain prose.** This is a floor: the summary still goes to the scoring provider (Jev). That is why legal review is mandatory.
