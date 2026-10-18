---
sidebar_position: 2
---

# Known Limits and Open Work

This page lists the **real gaps** found while verifying the documentation against the code, and work not yet done. It is kept so that there is an honest "where the product is today" table. When an item is resolved it is removed from here.

*Last verification: 18 October 2026.*

## About the product

| Topic | Status | Effect |
|---|---|---|
| **In-app backup is SQLite only** | `api/backup.py` backs up only the SQLite file. All Docker installations use PostgreSQL | On PostgreSQL, Settings → Backup Now does not work; `pg_dump` is needed separately |
| **`ENCRYPTION_KEY` is not used** | `.env.example` and `setup-env.sh` generate it, the code does not read it. The real key is `data/.secret` | Misleading; `data/.secret` must be included in backups |
| **Instance-level settings are not per company** | Provider keys, database connections, backup and social-media settings are installation-wide; for them `require_manager` accepts a managing role in any company | In a multi-company installation a manager of one company can touch these settings. This release targets single-organisation self-hosting; hosted multi-tenant use needs these settings tied to a company |
| **Telegram: one bot** | The interactive bot runs on the first active configuration's token; if several companies configure their own bot only one receives updates. A chat is authorised as a whole, not each sender | Use a single bot in a multi-company installation; per-person pairing is planned |
| **Telegram buttons** | The task/A2A approval buttons do not use the atomic transition of the HTTP endpoints | If two places decide at once the last writer may win |
| **Assistant view limits** | `assistant_user` restricts only when it is the person's only role; with another role the restriction lifts (roles union). The stream is reduced to status events, but raw tool arguments/results are stored server-side. Outputs list/download, the sources panel and the local Assistant folder helper do not exist yet | Raw data is read only with management rights; the view is the first slice of ADR-0022 |
| **Draft agent concurrency** | A department head may edit a `draft` agent while an approver activates it; the write does not lock the status | A short edit can slip into a just-activated agent; at runtime only `active` agents are used |
| **No link to the Inbox in the sidebar** | `/inbox` opens only at sign-in for the `user` role | Other roles type the address by hand |
| **No manager password-reset button** | `POST /auth/reset/{id}` exists, not in the interface | API only |
| **No interface for the policy engine mode** | `off/dry_run/enforce` through `PUT /policies/config` | API needed for enforcement |
| **A2A requests produce no notification** | No Inbox/Telegram notification (except `/onaylar` in the Telegram bot) | The approver may not notice pending work |
| **`text_to_chart` is a placeholder, `code_execution` deferred** | "Chart Generation" appears in the tool list but does not produce a chart | Expectation management |
| **Tool use in flows only for the Anthropic protocol** | A single call without tools on other providers | Flows cannot use tools on some models |
| **The `function` skill is not fully isolated** | Restricted namespace + timeout, no process isolation | Untrusted code must not be run |
| **Git: GitHub only** | Change-request commits fail outside GitHub; the interface also offers GitLab/Gitea | A local git is planned |

## fab (department workspace)

| Topic | Status |
|---|---|
| Real workspace runtime | None; only a `FakeRuntime` for tests |
| Workspace image | Not run in Docker |
| Rating and calibration | Not measured with live Jev; thresholds are proposals |
| Filtering | Looks only at shape; does not recognize names/addresses |
| Legal review | Mandatory (KVKK/GDPR) before rating and sharing with the manager are turned on |
| Missing `fab` screens | Rubric view, unit findings, shared signals, the person who resolves a contest |

Details: [fab → Administrator Guide](/fab/enablement).

## Documentation and process

| Topic | Status |
|---|---|
| `docs/ROADMAP.md` | Current (30 September 2026) |
| `NOTLAR.md` (in the repo) | Left from June 2026; contains items no longer valid such as SQLite and "no audit log". The current summary is in [Developer Notes](/developer-notes/overview) |
| First policy-digest attempt | The old ADR-0014–0017 drafts and code (`PolicyClause`, `CompanySchema`, `PromptFlag`) were not merged; because their ADR numbers clash with the new ADRs they sit on a local branch |
