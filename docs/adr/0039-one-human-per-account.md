# ADR-0039: One account is one human in a company

- **Status:** proposed
- **Date:** 2026-11-03
- **Deciders:** Fabrika / fab.engineering
- **Related:** ADR-0028 (`/me/workspace`), ADR-0035 (reports), ADR-0037

## Context

`person_for_user` resolves "which person is calling" from the session: the account's human
`Personnel` record in the company. It took the first match. Nothing stops two human records in the
same company from pointing at one account (`Personnel.user_id` is a soft link; the invite flow
writes it without checking). With two, the caller silently became whichever row came first: its
profile, its manifest, its files and its drift report. Found while reviewing `/me/workspace`
(Codex, authorisation pass).

## Decision

1. **Ambiguity is an error.** If an account has more than one human `Personnel` in the resolved
   company, `person_for_user` answers `409` ("More than one personnel record is linked to this
   account"). It never picks one, and ordering the rows would not make the identity clear. Agent
   records on an account are not humans and do not count. It is shared by every endpoint that
   resolves the caller (workspace, files, report, work review, assistant), so all of them stop
   rather than act as the wrong person.
2. **The invite flow cannot create the ambiguity.** Inviting a person whose resulting account is
   already linked to another human record of the same company answers `409` and changes nothing
   (membership, password and link are rolled back). The check and the link are serialised per account and company: `link_human` first writes the account's membership row, which takes a write lock (SQLite and PostgreSQL alike), so a second invite for the same account waits until the first commits and then sees its link. Two invites at once therefore give one success and one `409`.
3. **A person can still belong to several companies,** one record in each; `company_id` chooses.

## What this does not do

- It does not repair existing duplicates: an administrator unlinks one record (the affected person
  sees `409` until then). There is no database unique key yet because existing data may already
  contain duplicates and a migration must not fail on them; a cleaned deployment can add one later.
- The serialisation holds only for invites; it is not a database constraint.
- Other ways to set `Personnel.user_id` (direct edits, imports) are not guarded here; the read side
  refuses ambiguity regardless.

## Verification

`backend/tests/test_one_human_per_account.py`: two human records on one account give `409` on the
manifest, file and report endpoints; another account is unaffected; an agent record on the same
account is not a second human; one account in two companies still works (and needs `company_id`);
two invites released together through a barrier link only one person (the test fails when the lock is removed; the same race runs on PostgreSQL in `test_pg_smoke.py`); the invite refuses a second link and leaves the link, the membership and the password untouched;
the query cannot choose a role, department or person (the session's membership decides).
