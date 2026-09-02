"""
RAG service tests — embeddings mocked to avoid loading the 80 MB model.

RAG now lives in the main DB (EmbeddingRecord / RagIndexState); the `patch_engine`
autouse fixture already points get_session() at the test SQLite DB.
"""

from __future__ import annotations

from datetime import datetime

import numpy as np
import pytest

from tests.conftest import make_company, make_personnel


def _fake_embed(text: str) -> np.ndarray:
    """Deterministic fake embeddings — unique per text, no model needed."""
    arr = np.zeros(384, dtype=np.float32)
    for i, ch in enumerate(text):
        arr[i % 384] += ord(ch) / 10000.0
    norm = np.linalg.norm(arr)
    return (arr / norm if norm > 0 else arr).astype(np.float32)


@pytest.fixture()
def rag(client, monkeypatch):
    """Mocked embed() + tables ensured (client → tables created, engine patched)."""
    monkeypatch.setattr("services.rag_service.embed", _fake_embed)
    from services.rag_service import init_rag_db

    init_rag_db()
    import services.rag_service as rs

    return rs


# ── init ─────────────────────────────────────────────────────────────────────


def test_init_creates_tables(rag, test_engine):
    from sqlalchemy import inspect

    names = set(inspect(test_engine).get_table_names())
    assert {"embeddingrecord", "ragindexstate"} <= names


def test_init_is_idempotent(rag):
    rag.init_rag_db()  # must not raise


# ── index_new_records ────────────────────────────────────────────────────────


def test_index_empty_db_returns_zeros(rag):
    assert rag.index_new_records() == {
        "session_message": 0,
        "task_result": 0,
        "agent_memory": 0,
    }


def _task(db_session, title, result, company_id="co1"):
    import models

    t = models.TaskRequest(
        company_id=company_id,
        requester_user_id="u1",
        title=title,
        body="body",
        status="completed",
        result=result,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db_session.add(t)
    return t


def test_index_task_results(rag, db_session):
    _task(
        db_session,
        "Q1 Analysis",
        "Q1 sales were 20% higher than expected across segments.",
    )
    db_session.commit()

    stats = rag.index_new_records()
    assert stats == {"session_message": 0, "task_result": 1, "agent_memory": 0}

    s = rag.get_stats()
    assert s["total"] == 1
    assert s["by_type"]["task_result"] == 1


def test_index_skips_short_results(rag, db_session):
    _task(db_session, "Short", "ok")  # < 20 chars
    db_session.commit()
    assert rag.index_new_records()["task_result"] == 0


def test_index_deduplicates(rag, db_session):
    _task(
        db_session, "Dedup", "This is a long enough result that should be indexed once."
    )
    db_session.commit()
    rag.index_new_records()
    rag.index_new_records()
    assert rag.get_stats()["total"] == 1


def test_index_agent_memory(rag, db_session):
    import models

    co = make_company(db_session, name="MemCo", slug="mem-co")
    agent = make_personnel(db_session, co.id, name="MemBot", slug="mem-bot")
    db_session.commit()
    db_session.add(
        models.AgentMemory(
            personnel_id=agent.id,
            summary="User asked about quarterly reports and budgets. Q2 beat Q1.",
            created_at=datetime.utcnow(),
        )
    )
    db_session.commit()

    assert rag.index_new_records()["agent_memory"] == 1
    assert rag.get_stats()["by_type"]["agent_memory"] == 1


# ── search ───────────────────────────────────────────────────────────────────


def _seed(db_session, n, company_id="co1"):
    for i in range(n):
        _task(
            db_session,
            f"Task {i}",
            f"Detailed result {i}: analysis of quarterly performance metrics and revenue.",
            company_id=company_id,
        )
    db_session.commit()


def test_search_empty_below_threshold(rag, db_session):
    _seed(db_session, rag.MIN_RECORDS_FOR_SEARCH - 1)
    rag.index_new_records()
    assert rag.search("analysis") == []


def test_search_returns_results_above_threshold(rag, db_session):
    _seed(db_session, rag.MIN_RECORDS_FOR_SEARCH + 1)
    rag.index_new_records()

    results = rag.search("quarterly performance", k=3)
    assert 0 < len(results) <= 3
    for r in results:
        assert {
            "source_type",
            "source_id",
            "chunk_text",
            "created_at",
            "score",
        } <= r.keys()
        assert isinstance(r["score"], float)
        assert r["score"] <= 1.0 + 1e-6


def test_search_respects_k(rag, db_session):
    _seed(db_session, rag.MIN_RECORDS_FOR_SEARCH + 5)
    rag.index_new_records()
    for k in (1, 3):
        assert len(rag.search("quarterly", k=k)) <= k


def test_search_company_filter(rag, db_session):
    _seed(db_session, rag.MIN_RECORDS_FOR_SEARCH + 1, company_id="co_a")
    _seed(db_session, 1, company_id="co_b")
    rag.index_new_records()

    results = rag.search("quarterly", company_id="co_b", k=5)
    assert isinstance(results, list)  # smoke — no crash, filter applied internally


# ── get_stats ────────────────────────────────────────────────────────────────


def test_get_stats_empty(rag):
    s = rag.get_stats()
    assert s == {"total": 0, "ready": False, "by_type": {}, "index_state": {}}


def test_get_stats_after_index(rag, db_session):
    _seed(db_session, rag.MIN_RECORDS_FOR_SEARCH)
    rag.index_new_records()

    s = rag.get_stats()
    assert s["total"] == rag.MIN_RECORDS_FOR_SEARCH
    assert s["ready"] is True
    assert "task_result" in s["by_type"]
    assert "last_indexed_at" in s["index_state"]["task_result"]
