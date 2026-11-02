# ADR-0034: Monitoring summary (one screen from existing views)

- **Status:** proposed
- **Date:** 2026-11-02
- **Deciders:** Fabrika / fab.engineering
- **Related:** ADR-0026 (decision 8: monitoring combines existing views, it is not the observability
  product ADR-0022 §11 excluded), ADR-0004 (gateway usage), ADR-0006 (audit anchors), ADR-0023
  (evaluation), ADR-0027/0028 (workspace signing)

## Context

The pieces an operator needs to answer "is it healthy and is it still trustworthy?" exist but are
spread over per-agent or per-chain endpoints, each with its own authorisation. ADR-0026 asks for them
on one screen, explicitly without inventing a metrics stack.

## Decision

1. **One endpoint, `GET /admin/monitoring?company_id=...[&deep=true]`**, answering for exactly one
   company. Allowed only for a **company-wide founder or executive** of that company
   (`authz.require_role(..., FINAL, company_wide=True)`): 401 anonymous, 404 for someone who is not a
   member (existence is not revealed), 403 for a member without the role - including a department-scoped
   executive. Every query is bounded by that company id.
2. **Sections, each independent, each with a status** (`ok` / `warn` / `fail` / `unknown`); the overall
   status is the worst one (`fail` > `warn` > `unknown` > `ok`):
   - `service`: version and database reachability.
   - `audit`: event count of the company's chain and its **external-anchor state** (ADR-0006:
     truncation and rewrite, the thing a self-consistent rebuilt chain defeats). A chain with events
     but no anchor is `warn`. The full re-hash reads every event, so it runs only with `deep=true`;
     otherwise `verified` is `null` ("not checked in this request"), never "true".
   - `gateway`: today and this month, requests and tokens, summed over **this company's** agents
     only, with the top agents of the day.
   - `eval`: the last 30 days of stored diagnoses of this company, with the stage-1 suspect-layer
     counts, labelled as hypotheses, not fault rates (ADR-0023).
   - `workspace`: whether the signing material loads, epoch, CRL number, days left on the signing
     certificate (`warn` under 14), people issued a manifest and when last.
   - `clients`: **`unknown`, reason `drift_not_reported`** - clients do not report their state yet
     (ADR-0026 decision 4). It says so instead of guessing.
3. **A failing section never fails the response and never leaks.** An unexpected error in one section
   yields `{status: unknown, reason: section_failed}` (the detail goes to the server log); the
   workspace section exposes only a short stable code, no paths, no key material, no exception text.
4. **A page in the web app** (`/monitoring`, shown to executive and founder) renders the sections in
   Turkish, with a refresh and a "verify the whole chain" button. It adds no new measurements.

## What this does not do

- No time series, alerting, uptime probing or log search; no per-person data beyond agent names in the
  usage list; no cross-company view (a platform operator view is a different authorisation question).
- The audit chain is not re-hashed by default; a tampered event is found by `deep=true`, not by the
  cheap check (the anchor check catches truncation and head rewrites).
- `clients` stays `unknown` until drift reporting exists.

## Verification

`backend/tests/test_monitoring.py`: anonymous / outsider / other-company founder / plain member /
department-scoped executive; response shape and absence of secret-looking material; gateway and eval
and workspace counts that exclude other companies and out-of-window rows; the audit states (no events,
unanchored, anchored, tamper found only by `deep`, truncation after an anchor), and that another
company's chain is untouched; a section that raises is reported `unknown` without leaking the message.
