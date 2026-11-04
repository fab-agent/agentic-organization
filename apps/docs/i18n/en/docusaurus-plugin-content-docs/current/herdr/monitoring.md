---
sidebar_position: 4
---

# Monitoring

> ADR-0034 · ADR-0035 · ADR-0038 (proposed)

`GET /admin/monitoring?company_id=[&deep=true]` gives the state of one company at a glance. Only that company's **company-wide founder or executive** can see it (anonymous 401, non-member 404, missing role 403; a department-scoped executive also gets 403). The same view is the `/monitoring` page in the web app.

Each section is `ok`, `warn`, `fail` or `unknown`; the overall status is the worst one. A section that errors does not break the response: it returns `unknown / section_failed` and the detail goes only to the server log.

| Section | What it shows |
|---|---|
| `service` | Version, database reachability |
| `audit` | Event count and external-anchor state; the whole chain is re-hashed only with `deep=true` (otherwise `verified: null`) |
| `gateway` | Requests/tokens today and this month, top agents; only rows whose *recorded company id* matches |
| `eval` | Diagnoses of the last 30 days; hypotheses, not fault rates |
| `workspace` | Whether the signing material loads, epoch, CRL number, days left on the certificate (under 14 is `warn`) |
| `sessions` | Sessions alive in the last 5 minutes; how many have a ready policy and how many do not |
| `clients` | Drift the clients **report about themselves**; `unknown` if nobody has reported |

### "Alive" is not the same as "policy ready"

While `3pa run` is running it sends a heartbeat about every 30 seconds. The server records an authenticated heartbeat even when its policy is not ready (a revoked or invalid token records nothing) and adds `policy_ready`, `policy_reason` (fixed codes: `scope_unreadable`, `invalid_mode`, `invalid_default_effect`, `policy_unreadable`, `policy_malformed`) and `policy_mode` to the answer. "Not ready" means *the policy is broken and calls may be denied*, not that every call is denied. `3pa run` prints one line when the state changes and does not stop the sandbox because of that change (an unreachable gateway is a separate rule). Readiness is what the server could resolve at that moment; it does not prove that the machine or the local opencode obeys the policy.

### What this page does not do

There is no time series, alerting, uptime probing, log search or cross-company view. The `clients` section is a self-report, not a measurement.
