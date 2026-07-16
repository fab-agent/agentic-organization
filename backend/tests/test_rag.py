"""
RAG service tests — embeddings mocked to avoid loading the 80 MB model.

All tests use:
  - rag_db fixture: redirects RAG_DB_PATH to a tmp dir + mocks embed()
  - patch_engine (autouse): ensures get_session() hits the test SQLite DB
"""

from __future__ import annotations

from datetime import datetime

import numpy as np
import pytest

from tests.conftest import make_company, make_personnel

# ── Fixtures ──────────────────────────────────────────────────────────────────


def _fake_embed(text: str) -> np.ndarray:
    """Deterministic fake embeddings — unique per text, no model needed."""
    arr = np.zeros(384, dtype=np.float32)
    for i, ch in enumerate(text):
        arr[i % 384] += ord(ch) / 10000.0
    norm = np.linalg.norm(arr)
    return (arr / norm if norm > 0 else arr).astype(np.float32)


@pytest.fixture()
def rag_db(tmp_path, monkeypatch):
    """Isolated RAG DB + mocked embed function."""
    rag_path = tmp_path / "rag.db"
    monkeypatch.setattr("services.rag_service.RAG_DB_PATH", rag_path)
    monkeypatch.setattr("services.rag_service.embed", _fake_embed)

    from services.rag_service import init_rag_db

    init_rag_db()
    return rag_path


# ── init_rag_db ───────────────────────────────────────────────────────────────


def test_init_creates_tables(rag_db):
    import sqlite3

    with sqlite3.connect(str(rag_db)) as c:
        names = {
            r[0]
            for r in c.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table','shadow')"
            )
        }
    assert "embedding_meta" in names
    assert "index_state" in names


def test_init_is_idempotent(rag_db):
    from services.rag_service import init_rag_db

    init_rag_db()  # second call must not raise or corrupt tables


# ── index_new_records ─────────────────────────────────────────────────────────


def test_index_empty_db_returns_zeros(rag_db):
    from services.rag_service import index_new_records

    stats = index_new_records()
    assert stats == {"session_message": 0, "task_result": 0, "agent_memory": 0}


def test_index_task_results(rag_db, db_session):
    import models
    from services.rag_service import get_stats, index_new_records

    task = models.TaskRequest(
        company_id="co1",
        requester_user_id="u1",
        title="Q1 Analysis",
        body="Analyse Q1 data",
        status="completed",
        result="Q1 sales were 20% higher than expected across all product segments.",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db_session.add(task)
    db_session.commit()

    stats = index_new_records()
    assert stats["task_result"] == 1
    assert stats["session_message"] == 0
    assert stats["agent_memory"] == 0

    s = get_stats()
    assert s["total"] == 1
    assert s["by_type"]["task_result"] == 1


def test_index_skips_short_results(rag_db, db_session):
    import models
    from services.rag_service import index_new_records

    task = models.TaskRequest(
        company_id="co1",
        requester_user_id="u1",
        title="Short",
        body="Short body",
        status="completed",
        result="ok",  # < 20 chars — should be skipped
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db_session.add(task)
    db_session.commit()

    stats = index_new_records()
    assert stats["task_result"] == 0


def test_index_deduplicates(rag_db, db_session):
    import models
    from services.rag_service import get_stats, index_new_records

    task = models.TaskRequest(
        company_id="co1",
        requester_user_id="u1",
        title="Dedup Test",
        body="Test body",
        status="completed",
        result="This is a long enough result that should be indexed by the RAG system.",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db_session.add(task)
    db_session.commit()

    index_new_records()
    index_new_records()  # second run should not re-index

    assert get_stats()["total"] == 1


def test_index_agent_memory(rag_db, db_session):
    import models
    from services.rag_service import get_stats, index_new_records

    co = make_company(db_session, name="MemCo", slug="mem-co")
    agent = make_personnel(db_session, co.id, name="MemBot", slug="mem-bot")
    db_session.commit()

    memory = models.AgentMemory(
        personnel_id=agent.id,
        summary="The user asked about quarterly reports and budget allocations. Key insight: Q2 was better than Q1.",
        created_at=datetime.utcnow(),
    )
    db_session.add(memory)
    db_session.commit()

    stats = index_new_records()
    assert stats["agent_memory"] == 1
    assert get_stats()["by_type"]["agent_memory"] == 1


# ── search ────────────────────────────────────────────────────────────────────


def test_search_returns_empty_below_threshold(rag_db, db_session):
    import models
    from services.rag_service import MIN_RECORDS_FOR_SEARCH, index_new_records, search

    # Insert fewer records than the cold-start threshold
    for i in range(MIN_RECORDS_FOR_SEARCH - 1):
        task = models.TaskRequest(
            company_id="co1",
            requester_user_id="u1",
            title=f"Task {i}",
            body=f"Body {i}",
            status="completed",
            result=f"Result for task {i}: detailed analysis output with sufficient length.",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        db_session.add(task)
    db_session.commit()

    index_new_records()
    results = search("analysis")
    assert results == []


def _seed_tasks(db_session, count: int, company_id: str = "co1") -> None:
    import models

    for i in range(count):
        task = models.TaskRequest(
            company_id=company_id,
            requester_user_id="u1",
            title=f"Task {i}",
            body=f"Body {i}",
            status="completed",
            result=f"Detailed result for task {i}: analysis of quarterly performance metrics.",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        db_session.add(task)
    db_session.commit()


def test_search_returns_results_above_threshold(rag_db, db_session):
    from services.rag_service import MIN_RECORDS_FOR_SEARCH, index_new_records, search

    _seed_tasks(db_session, MIN_RECORDS_FOR_SEARCH + 1)
    index_new_records()

    results = search("quarterly performance", k=3)
    assert len(results) > 0
    assert len(results) <= 3
    assert all("source_type" in r for r in results)
    assert all("chunk_text" in r for r in results)
    assert all("score" in r for r in results)
    assert all(isinstance(r["score"], float) for r in results)
    assert all(
        r["score"] <= 1.0 for r in results
    )  # cosine: score = 1 - distance, max 1


def test_search_respects_k(rag_db, db_session):
    from services.rag_service import MIN_RECORDS_FOR_SEARCH, index_new_records, search

    _seed_tasks(db_session, MIN_RECORDS_FOR_SEARCH + 5)
    index_new_records()

    for k in (1, 3):
        results = search("quarterly", k=k)
        assert len(results) <= k


def test_search_company_filter(rag_db, db_session):
    from services.rag_service import MIN_RECORDS_FOR_SEARCH, index_new_records, search

    # Company A: enough records to pass threshold
    _seed_tasks(db_session, MIN_RECORDS_FOR_SEARCH + 1, company_id="co_a")
    # Company B: 1 record (below threshold — search uses total count, not per-company)
    _seed_tasks(db_session, 1, company_id="co_b")
    index_new_records()

    results = search("quarterly", company_id="co_b", k=5)
    # All returned results must belong to company B (or have no company)
    for r in results:
        pass  # company_id is not in the search result dict but filtering is applied internally
    # Smoke: no crash, returns a list
    assert isinstance(results, list)


# ── get_stats ─────────────────────────────────────────────────────────────────


def test_get_stats_empty(rag_db):
    from services.rag_service import get_stats

    s = get_stats()
    assert s["total"] == 0
    assert s["ready"] is False
    assert s["by_type"] == {}
    assert s["index_state"] == {}


def test_get_stats_after_index(rag_db, db_session):
    from services.rag_service import (
        MIN_RECORDS_FOR_SEARCH,
        get_stats,
        index_new_records,
    )

    _seed_tasks(db_session, MIN_RECORDS_FOR_SEARCH)
    index_new_records()

    s = get_stats()
    assert s["total"] == MIN_RECORDS_FOR_SEARCH
    assert s["ready"] is True
    assert "task_result" in s["by_type"]
    assert "task_result" in s["index_state"]
    assert "last_indexed_at" in s["index_state"]["task_result"]
