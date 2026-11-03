"""
PostgreSQL smoke — runs only when DATABASE_URL points at Postgres (the
`postgres.yml` CI job). Covers what SQLite can't: the Alembic chain on real PG,
pgvector search, and the audit-chain advisory lock path.

This test does NOT use conftest's SQLite engine — it talks to the real engine
built from DATABASE_URL.
"""

from __future__ import annotations

import os

import numpy as np
import pytest

pytestmark = pytest.mark.skipif(
    "postgresql" not in os.getenv("DATABASE_URL", ""),
    reason="Postgres-only smoke",
)


@pytest.fixture(autouse=True)
def patch_engine():
    """
    Override conftest's autouse SQLite engine patch — this module must run
    against the real Postgres engine built from DATABASE_URL.
    """
    yield


@pytest.fixture(scope="module")
def pg():
    """Fresh schema via the real init_db() path + RAG pgvector setup."""
    from sqlmodel import SQLModel

    import database
    import models  # noqa: F401  (register tables)

    # Emulate a fresh deploy: create all tables, stamp head (matches init_db()).
    SQLModel.metadata.drop_all(database.engine)
    from alembic import command
    from alembic.config import Config

    cfg = Config("alembic.ini")

    # Build the state at revision 7ed610efc189 (create_all, the way the app's
    # fresh-DB path does), then run every migration after it on real Postgres.
    # Keep this in sync with the migrations added by this branch.
    added_since = {
        "auditevent",
        "policyconfig",
        "embeddingrecord",
        "ragindexstate",
        "gatewayusage",
        "auditseverity",
        "revokedtoken",
        "personatokenstate",
        "personaheartbeat",
        "personacommand",
        # workspaces, work review and fit rating (ADR-0018 / 0019 / 0021)
        "workspace",
        "worksignal",
        "worknote",
        "workrating",
        "worktrainingshare",
        # stored run diagnosis (ADR-0023)
        "rundiagnosis",
        "harnessartifact",
        "learningsignal",
    }
    base = [t for n, t in SQLModel.metadata.tables.items() if n not in added_since]
    SQLModel.metadata.create_all(database.engine, tables=base)
    # Migration c9e5a3b72d14 adds columns to tables that already exist in the base state;
    # create_all above already built them, so take them out to match revision 7ed610efc189.
    from sqlalchemy import text

    with database.engine.begin() as conn:
        conn.execute(text("DROP INDEX IF EXISTS uq_agentconfig_workspace_agent"))
        conn.execute(
            text("ALTER TABLE personnel DROP COLUMN IF EXISTS job_description")
        )
        conn.execute(
            text("ALTER TABLE agentconfig DROP COLUMN IF EXISTS is_workspace_agent")
        )
    command.stamp(cfg, "7ed610efc189")
    command.upgrade(cfg, "head")

    from services.rag_service import init_rag_db

    init_rag_db()
    yield
    SQLModel.metadata.drop_all(database.engine)


def test_migrations_reached_head(pg):
    from sqlalchemy import inspect

    import database

    names = set(inspect(database.engine).get_table_names())
    assert {"auditevent", "policyconfig", "embeddingrecord", "ragindexstate"} <= names
    assert {
        "workspace",
        "worksignal",
        "worknote",
        "workrating",
        "worktrainingshare",
        "rundiagnosis",
        "harnessartifact",
        "learningsignal",
    } <= names


def test_audit_chain_on_postgres(pg):
    from services import audit_chain

    for i in range(5):
        audit_chain.append(
            actor_type="agent",
            action="tool_event",
            company_id="co-pg",
            target="bash",
            payload={"i": i},
        )
    r = audit_chain.verify("co-pg")
    assert r["ok"] is True and r["count"] == 5


def test_pgvector_search(pg, monkeypatch):
    import services.rag_service as rs

    def fake_embed(text: str) -> np.ndarray:
        arr = np.zeros(rs.EMBEDDING_DIM, dtype=np.float32)
        for i, ch in enumerate(text):
            arr[i % rs.EMBEDDING_DIM] += ord(ch) / 10000.0
        n = np.linalg.norm(arr)
        return (arr / n if n else arr).astype(np.float32)

    monkeypatch.setattr(rs, "embed", fake_embed)

    from datetime import datetime

    from database import get_session
    from models import Company, TaskRequest, User

    with get_session() as s:
        co = Company(name="PG Co", slug="pg-co")
        u = User(email="pg@smoke.test", name="PG", is_active=True)
        s.add(co)
        s.add(u)
        s.flush()
        for i in range(rs.MIN_RECORDS_FOR_SEARCH + 2):
            s.add(
                TaskRequest(
                    company_id=co.id,
                    requester_user_id=u.id,
                    title=f"T{i}",
                    body="b",
                    status="completed",
                    result=f"Detailed quarterly revenue analysis number {i} with enough text.",
                    created_at=datetime.utcnow(),
                    updated_at=datetime.utcnow(),
                )
            )
        s.commit()

    rs.index_new_records()
    assert rs._is_postgres() is True
    results = rs.search("quarterly revenue", k=3)
    assert 0 < len(results) <= 3
    assert all(r["score"] <= 1.0 + 1e-6 for r in results)


def test_change_request_dept_head_is_a_user_id(pg):
    """dept_head_id stores the approving user; the FK must point at user.id."""
    from sqlmodel import Session

    import database
    from models import ChangeRequest, Company, Personnel, User

    with Session(database.engine) as s:
        co = Company(name="CR Co", slug="cr-co")
        user = User(email="cr@pg.test", name="CR", password_hash="x")
        s.add_all([co, user])
        s.flush()
        person = Personnel(
            company_id=co.id, name="A", slug="a", title="t", role="r", type="agent"
        )
        s.add(person)
        s.flush()
        s.add(
            ChangeRequest(
                company_id=co.id,
                personnel_id=person.id,
                change_type="skill",
                title="t",
                proposed_json="{}",
                dept_head_id=user.id,
            )
        )
        s.commit()


def test_harness_activation_race_has_one_winner(pg):
    """Two writers on one logical key: B commits v1 after A looked and before A wrote."""
    from sqlmodel import Session

    import database
    from models import Company, HarnessArtifact, Personnel
    from services import harness as h

    with Session(database.engine) as setup:
        co = Company(name="H Co", slug="h-co")
        setup.add(co)
        setup.flush()
        agent = Personnel(
            company_id=co.id, name="A", slug="a-h", title="t", role="r", type="agent"
        )
        setup.add(agent)
        setup.commit()
        company_id, agent_id = co.id, agent.id

    def art(version, text):
        return HarnessArtifact(
            company_id=company_id,
            level="person",
            target_id=agent_id,
            kind="prompt_text",
            key="main",
            version=version,
            content=text,
            content_hash=h.content_hash(text),
            status="active",
        )

    a = Session(database.engine)
    b = Session(database.engine)
    try:
        assert (
            a.query(HarnessArtifact).filter_by(company_id=company_id).count() == 0
        )  # A looks
        h._install(b, art(1, "from B"), None)
        b.commit()  # B wins
        with pytest.raises(h.HarnessError):
            h._install(a, art(2, "from A"), None)  # A allocated v2 after B committed
        a.rollback()
    finally:
        a.close()
        b.close()
    with Session(database.engine) as check:
        rows = check.query(HarnessArtifact).filter_by(company_id=company_id).all()
        assert [(r.version, r.status) for r in rows] == [(1, "active")]


def test_drift_report_race_has_one_winner(pg):
    """ADR-0035: several requests that all saw an old report - or none - write at most one."""
    import threading
    from datetime import datetime, timedelta

    from sqlmodel import Session, select

    import database
    from api.me_workspace import store_report
    from models import Company, Personnel, WorkspaceClientReport

    with Session(database.engine) as setup:
        co = Company(name="R Co", slug="r-co")
        setup.add(co)
        setup.flush()
        p = Personnel(
            company_id=co.id, name="P", slug="p-r", title="t", role="r", type="human"
        )
        setup.add(p)
        setup.commit()
        cid, pid = co.id, p.id

    def base(n):
        return dict(
            client_version="1.0",
            epoch=1,
            generation=n,
            missing=n,
            modified=0,
            extra=0,
            unmanaged=0,
            interrupted=False,
        )

    def race(n_threads, now):
        results, barrier = [], threading.Barrier(n_threads)

        errors = []

        def worker(i):
            try:
                with Session(database.engine) as s:
                    barrier.wait()
                    results.append((i, store_report(s, cid, pid, base(i + 1), now)))
            except Exception as e:  # a worker that died must fail the test, not vanish
                errors.append(e)

        ts = [threading.Thread(target=worker, args=(i,)) for i in range(n_threads)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        assert not errors, errors
        assert len(results) == n_threads  # every writer answered
        return results

    now = datetime.utcnow()
    first = race(8, now)  # no row yet
    assert sum(1 for _, ok in first if ok) == 1
    assert sum(1 for _, ok in first if not ok) == 7
    with Session(database.engine) as s:
        rows = s.exec(
            select(WorkspaceClientReport).where(WorkspaceClientReport.person_id == pid)
        ).all()
        assert len(rows) == 1
        winner = [i for i, ok in first if ok][0]
        assert rows[0].missing == winner + 1
    later = now + timedelta(seconds=45)  # the row is old now
    second = race(8, later)
    assert sum(1 for _, ok in second if ok) == 1
    assert sum(1 for _, ok in second if not ok) == 7
    with Session(database.engine) as s:
        row = s.exec(
            select(WorkspaceClientReport).where(WorkspaceClientReport.person_id == pid)
        ).one()
        assert row.missing == [i for i, ok in second if ok][0] + 1


def test_manifest_issue_slot_race_has_one_winner(pg):
    """ADR-0037: eight requests that all see no/old stamp take the slot exactly once."""
    import threading
    from datetime import datetime, timedelta

    from sqlmodel import Session

    import database
    from api.me_workspace import claim_slot
    from models import Company, Personnel, WorkspaceIssueStamp

    with Session(database.engine) as setup:
        co = Company(name="I Co", slug="i-co")
        setup.add(co)
        setup.flush()
        p = Personnel(
            company_id=co.id, name="P", slug="p-i", title="t", role="r", type="human"
        )
        setup.add(p)
        setup.commit()
        cid, pid = co.id, p.id

    def race(now):
        results, errors = [], []
        barrier = threading.Barrier(8)

        def worker():
            try:
                with Session(database.engine) as s:
                    barrier.wait()
                    results.append(
                        claim_slot(
                            s,
                            WorkspaceIssueStamp,
                            "issued_at",
                            cid,
                            pid,
                            {},
                            now,
                            timedelta(seconds=10),
                        )
                    )
            except Exception as e:
                errors.append(repr(e))

        ts = [threading.Thread(target=worker) for _ in range(8)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        assert not errors, errors
        return results

    t0 = datetime.utcnow()
    assert race(t0).count(True) == 1  # first ever: the unique key decides
    assert race(t0 + timedelta(seconds=5)).count(True) == 0  # inside the window
    assert (
        race(t0 + timedelta(seconds=11)).count(True) == 1
    )  # after it: the UPDATE decides


def test_account_link_race_has_one_winner(pg):
    """ADR-0039: two invites that both pass the check cannot both link the account."""
    import threading

    from fastapi import HTTPException
    from sqlmodel import Session, select

    import database
    from api.personnel import link_human
    from models import Company, Personnel, User

    with Session(database.engine) as setup:
        co = Company(name="L Co", slug="l-co")
        u = User(email="l@test.com", name="L")
        setup.add_all([co, u])
        setup.flush()
        # no membership here on purpose: the lock must not depend on one existing
        ps = [
            Personnel(
                company_id=co.id,
                name=n,
                slug=f"l-{n}",
                title="t",
                role="r",
                type="human",
            )
            for n in ("a", "b", "c", "d")
        ]
        setup.add_all(ps)
        setup.commit()
        uid, cid, pids = u.id, co.id, [p.id for p in ps]

    barrier, out, errors = threading.Barrier(4), [], []

    def worker(pid):
        try:
            with Session(database.engine, expire_on_commit=False) as s:
                person = s.get(Personnel, pid)
                barrier.wait()
                try:
                    link_human(s, person, uid, cid)
                    out.append("linked")
                except HTTPException as e:
                    out.append(e.status_code)
        except Exception as e:
            errors.append(repr(e))

    ts = [threading.Thread(target=worker, args=(p,)) for p in pids]
    [t.start() for t in ts]
    [t.join(timeout=60) for t in ts]
    assert not errors, errors
    assert sorted(map(str, out)) == ["409", "409", "409", "linked"]
    with Session(database.engine) as s:
        assert len(s.exec(select(Personnel).where(Personnel.user_id == uid)).all()) == 1
