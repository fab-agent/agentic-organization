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
    }
    base = [t for n, t in SQLModel.metadata.tables.items() if n not in added_since]
    SQLModel.metadata.create_all(database.engine, tables=base)
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
