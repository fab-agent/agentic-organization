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
   - `gateway`: today and this month, requests and tokens, from the usage rows **recorded for this
     company** (the company on the row, written with it). A row with no recorded company (legacy)
     has no proof of ownership and is left out, not attributed to whatever company the persona
     belongs to today; a persona that changed company keeps its past usage with the company that
     incurred it. A row spans a period and is not split if a persona moves mid-period (a limit of
     the writer, `gateway_limits.record_usage`), with the top agents of the day.
   - `eval`: the last 30 days of stored diagnoses of this company, with the stage-1 suspect-layer
     counts, labelled as hypotheses, not fault rates (ADR-0023).
   - `workspace`: whether the signing material loads, epoch, CRL number, days left on the signing
     certificate, read from the certificate's verified payload (`warn` under 14), people issued a manifest and when last.
   - `clients`: **`unknown`, reason `drift_not_reported`** - clients do not report their state yet
     (ADR-0026 decision 4). It says so instead of guessing.
3. **A failing section never fails the response and never leaks.** An unexpected error in one section
   yields `{status: unknown, reason: section_failed}` (the detail goes to the server log); the
   workspace section shows a reason only if it is on an explicit list of the codes the signer loader
   can raise (its own codes and the `signing_` / `manifest_` families of manifest error codes); any
   other text - a message, a path, hex that merely looks like a code - becomes the fixed code
   `signing_unavailable`. A test scans the sources and fails when a new code is not on the list.
4. **A page in the web app** (`/monitoring`, shown only to a **company-wide** founder or executive of
   the active company, the same rule as the endpoint) renders the sections in
   Turkish, with a refresh and a "verify the whole chain" button. It adds no new measurements. Only the newest request for the company that is active now may
   update the screen (a late answer for the company just left is dropped; tested).

## What this does not do

- No time series, alerting, uptime probing or log search; no per-person data beyond agent names in the
  usage list; no cross-company view (a platform operator view is a different authorisation question).
- The audit chain is not re-hashed by default; a tampered event is found by `deep=true`, not by the
  cheap check (the anchor check catches truncation and head rewrites).
- `clients` stays `unknown` until drift reporting exists.

## Verification

`backend/tests/test_monitoring.py`: anonymous / outsider / other-company founder / plain member /
department-scoped executive; response shape and absence of secret-looking material; gateway counts that follow the row's recorded company (not the persona's current one; legacy rows
excluded), eval and workspace counts that exclude other companies and out-of-window rows, days left
from a real certificate envelope, reason codes; `frontend/tests/latest-request.test.mjs` for the
stale-answer rule; the audit states (no events,
unanchored, anchored, tamper found only by `deep`, truncation after an anchor), and that another
company's chain is untouched; a section that raises is reported `unknown` without leaking the message.
