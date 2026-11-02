# ADR-0035: Client drift report (a diagnostic signal, not attestation)

- **Status:** proposed
- **Date:** 2026-11-02
- **Deciders:** Fabrika / fab.engineering
- **Related:** ADR-0026 (decision 4: drift is a diagnostic signal; a same-user report is not device
  proof), ADR-0029 (`scanDrift`), ADR-0028 (`/me/workspace`), ADR-0034 (the `clients` section)

## Context

The provisioner can compare a person's Herdr app home with what it installed (`3pa workspace
status`), but nobody else can see the result: the monitoring page says `clients: unknown,
drift_not_reported`. ADR-0026 asks for drift and a missing heartbeat to be reported as a
diagnostic signal.

## Decision

1. **The client sends a small report; the server keeps only the latest per person.**
   `POST /me/workspace/report` (same web session as `GET /me/workspace`; the person and company are
   resolved from the session exactly as there, never from the body). Body, strict (unknown fields
   refused): `client_version`, `epoch`, `generation` (what the client says is installed),
   `missing`, `modified`, `extra`, `unmanaged` (counts) and `interrupted` (an update waits to be
   rolled back). **Counts only - no file names, paths or contents** leave the machine. One row per
   `(company, person)` is replaced on every accepted report; history is not kept.
2. **It is a claim, never a fact.** The server stores it as "reported", marks it so in every view,
   and **never uses it for any access, policy or signing decision**. A client that is compromised, or
   a user who wants to hide an edit, can send anything or nothing; the same user can alter the
   install record `scanDrift` compares against. A report proves that a cooperative client looked, not
   that the machine is as described (ADR-0026 decision 4). Stronger guarantees need OS-level
   application control.
3. **Bounded and cheap.** Counts are integers `0..100000`, `generation`/`epoch` are bounded, the
   version string is a short fixed alphabet. A second report from the same person within 30 seconds
   is refused (`429`, `Retry-After`) without writing, so a loop cannot churn the table; the row count
   is bounded by people, not by reports.
4. **The CLI reports after a successful sync** (best effort: a failure to report never fails or
   delays the sync, and says so in one line) and on demand with `3pa workspace report`
   (`--no-report` / `THREEPA_NO_REPORT=1` turn the automatic one off). The report is built from
   `scanDrift` and the installed record - it adds no new scanning.
5. **The `clients` section of the monitoring summary** (ADR-0034) stops saying "not reported": for
   the people who were issued a workspace it shows how many have reported, how many are **behind**
   (reported generation below the generation last issued - normal between syncs), how many have **not
   reported for 7 days** (a missing heartbeat is the only signal a silent client gives; leave is
   normal, so it is information, not a warning), and which people report drift (name and counts, at
   most 20). Status: `warn` when anyone reports drift or an interrupted update; `unknown` when
   nobody has reported yet; otherwise `ok`. Everything is labelled self-reported.

## What this does not do

- It does not verify the report, authenticate the device, or detect a client that stays silent or
  lies. Silence is shown (7 days), not punished.
- No file names, mod contents or error text; no history or trend; no push or alert.
- No policy consequence: drift never revokes a workspace or blocks a login.

## Verification

Server: strict body (extra fields, negative or huge numbers, bad version refused); the person comes
from the session (another person's id in the body is ignored/refused); a user with no personnel
record is refused; the 30 s limit writes nothing; replace-not-append; the monitoring section's
counts, behind/stale logic, name list cap, company isolation (another company's reports never
counted) and the claims-only wording. CLI: the payload is exactly the counts of `scanDrift` plus the
installed record, no names; a failing report does not fail the sync; the opt-outs; redirects
refused.
