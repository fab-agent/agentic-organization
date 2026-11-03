# ADR-0038: Heartbeat reports "alive" and "policy ready" separately

- **Status:** proposed
- **Date:** 2026-11-03
- **Deciders:** Fabrika / fab.engineering
- **Related:** ADR-0009 (`3pa run` heartbeat), ADR-0026 (fail-closed gate; this was listed as open),
  ADR-0034 (monitoring), ADR-0035 (client reports)

## Context

`POST /workstation/heartbeat` says a `3pa run` session is alive and returns the policy mode. It does
not say whether the policy can actually be applied. Since ADR-0026 an unreadable scope, an invalid
mode, an unreadable policy, an invalid default effect or a malformed policy block makes the gate deny tool calls (all of them for the first three; for a bad rule or block, those that reach it). Such a
session still pings, still looks alive, and nobody is told that its tool calls are being
denied (all of them, or those that reach the broken rule). If resolution failed inside the heartbeat itself, the call returned `500` after the ping
had already been written, so the client saw "gateway failing" for a policy problem.

## Decision

1. **A readiness check that follows the gate's own path.** `policy_engine.check_ready(persona_id)`
   resolves the scope, the mode and the applicable policies and parses their rules exactly as
   `decide` does, and evaluates nothing. Ready means that path succeeds and no block is malformed
   (mode `off` counts as ready: the gate allows before reading any policy). It uses the same static checks as the evaluator: a rule the evaluator would reject and an invalid default effect are not ready either. Otherwise it is not ready, with one of a
   fixed set of codes: `scope_unreadable`, `invalid_mode`, `invalid_default_effect`, `policy_unreadable`, `policy_malformed`.
   Exception text is never returned or stored.
2. **The heartbeat records both facts and never fails because of policy.** The ping (`last_seen`) is
   always written. The answer adds `policy_ready`, `policy_reason`, `policy_mode`;
   `fail_closed` is true when not ready (calls **may** be denied: all of them when the scope, mode, default effect or policy read is the problem; for a bad rule only the calls that reach it, because the evaluator checks a rule's fields as far as it matches) or in `enforce`. `ok` keeps
   its old meaning (the ping was recorded). Three nullable columns on `personaheartbeat` keep the
   last answer (`policy_ready` is `NULL` for sessions that predate the check).
3. **Monitoring gets a `sessions` section** (founder/executive only, same rule as the rest): sessions
   alive in the last 5 minutes, how many of them were ready at their last ping, how many were not
   (with name and fixed reason, at most 20), and how many were never checked. Status: `warn` when any
   live session is not ready; `ok` with reason `no_live_sessions` when nothing is live (normal at night; it must not degrade the whole view), `unknown` when live sessions
   are all unchecked; otherwise `ok`. Only the company's own sessions are counted. A stored reason
   that is not on the fixed list is shown as `policy_unreadable`.
4. **The CLI says it once.** When the answer flips to not ready, `3pa run` prints one line with the
   fixed code ("gateway is up but your policy cannot be applied right now ..."), and one line when it
   recovers. It does not stop the sandbox (the gate already denies what it denies; stopping is ADR-0009's separate
   fail-closed rule for an unreachable gateway).

## What this does not do

- "Ready" is what the **server** could resolve for that persona at the last ping. It says nothing
  about the machine, the sandbox or whether the local opencode obeys it (ADR-0003 limits).
- It is a point-in-time value: a policy edited after the last ping shows at the next ping (about 30 s).
- No history, alerting or auto-revocation; a session that stops pinging simply stops being alive.
- It does not change what the gate decides. Readiness is deliberately conservative: it checks every rule's fields statically, while the evaluator can skip a broken rule that never matches the call. So "not ready" means "the policy is broken and calls may be denied", not "every call is denied".

## Verification

`backend/tests/test_heartbeat_ready.py`: ready; malformed block; invalid mode; unknown persona; a
database error (reason fixed, error text absent); `off`; the ping is stored even when not ready (202,
`fail_closed` true); recovery replaces the earlier failure; the monitoring counts (alive vs ready),
a stale session is not alive, a session from before the check is "unchecked" and never ready,
another company's sessions are never counted, an out-of-list stored reason is not shown, the endpoint
carries the section and stays closed to anonymous callers; migration columns match the model.
`policy_mode` in the answer stays whenever the mode could be resolved, even if the policy read then fails (old clients keep their value). The CLI prints only words from a fixed list (reason codes and modes), whatever the server sends. Readiness and `decide` are tested against the same bad inputs (bad rule schema, bad default effect). The CLI message is not covered by an automated test (the heartbeat loop is not exported).
