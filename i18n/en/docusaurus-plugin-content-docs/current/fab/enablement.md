---
sidebar_position: 6
---

# Administrator Guide: Switches and Verification

The features below come **off per company**; the founder turns them on. Before turning them on, make sure the prerequisite is met.

| What | How | Prerequisite |
|---|---|---|
| Work review | `PUT /work-review/settings {"enabled": true, "acknowledge_notice": true}` | Employees have been informed |
| Rating | `PUT /work-review/settings {"rating_enabled": true, "acknowledge_notice": true}` | Work review is on, `TYPESAFE_API_KEY`, a calibrated rubric |
| Sharing with the manager | `PUT /work-review/training-need/settings {"sharing_enabled": true}` | Legal review |
| Intent classification | AppConfig `intent.enabled` + `TYPESAFE_API_KEY` | The request text leaves the company |
| Workspace runtime | `WORKSPACE_RUNTIME=fake` for tests only | The real one has not been written |

## Decisions needed before turning on

- **Legal review (KVKK / GDPR):** mandatory before rating and sharing are turned on.
- **Retention period and export authority** (default 365 days).
- **Minimum group size** (default 3): should it be permanent.
- Keys are given only as environment variables; they are not written to files or commits.

## Verification

```bash
# Backend (~6 min, run in the background)
cd backend && ruff check . && ruff format --check . && python -m pytest -q

# fab
cd packages/tui && cargo fmt --check && cargo clippy --all-targets -- -D warnings && cargo test

# fab end to end (over 2 min, needs pyte)
cargo build && python tests/e2e_sync.py
```

When PR #21 was merged on 29 September 2026: backend 931 tests passed (3 skipped), 104 `fab` unit tests, all 10 checks in CI green.

## Not verified

- The live Jev API: rating and calibration were tried only with a fake transport layer.
- All thresholds are proposals, not measured.
- Filtering looks only at shape (it does not recognize names and details in plain prose).
- The workspace image was not run in Docker.
- `fab` was tried only in a fake 24×110 terminal.

## Developer notes

- If a new migration adds a table, add it to the `added_since` list in `backend/tests/test_pg_smoke.py`; if it adds a column to an existing table, it must be dropped there. Otherwise the PostgreSQL CI check breaks with "relation already exists".
- From scratch on SQLite the whole Alembic chain does not work (because of an old migration); to try it: `create_all` + `alembic stamp <previous revision>` + `upgrade head`.
- Migration head: `f8c4e1b73a26`.
