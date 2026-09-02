"""
RAG service — local multilingual embeddings, stored in the main database.

History: this used a separate `data/rag.db` with the `sqlite-vec` extension.
As of the Postgres move it lives in the main DB (`EmbeddingRecord`), so there is
one database and no fragile C extension.

Search:
  - PostgreSQL → a shadow `embedding_vec vector(384)` column + HNSW index
    (added by migration); nearest-neighbour via the `<=>` cosine operator.
  - SQLite / anything else → brute-force cosine in NumPy over the candidate rows
    (fine at this app's scale — an org's own session history, k≈4).

Public API is unchanged: init_rag_db(), index_new_records(), search(), get_stats(),
embed(), MIN_RECORDS_FOR_SEARCH.
"""

from __future__ import annotations

import logging
from datetime import datetime

import numpy as np

logger = logging.getLogger("app")

MODEL_NAME = "paraphrase-multilingual-MiniLM-L12-v2"
EMBEDDING_DIM = 384
BATCH_SIZE = 200
MIN_RECORDS_FOR_SEARCH = 20
TOP_K_DEFAULT = 5

_model = None


def _get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer

        logger.info(
            "Loading RAG embedding model", extra={"extra": {"model": MODEL_NAME}}
        )
        _model = SentenceTransformer(MODEL_NAME)
        logger.info("RAG embedding model ready")
    return _model


def embed(text: str) -> np.ndarray:
    return _get_model().encode(text, normalize_embeddings=True).astype(np.float32)


# ── Backend detection ────────────────────────────────────────────────────────


def _is_postgres() -> bool:
    try:
        from database import engine

        return engine.dialect.name == "postgresql"
    except Exception:
        return False


def _vec_literal(vec: np.ndarray) -> str:
    """pgvector text literal, e.g. '[0.1,0.2,...]' — cast with ::vector in SQL."""
    return "[" + ",".join(f"{x:.7f}" for x in vec.tolist()) + "]"


def init_rag_db() -> None:
    """
    Ensure the embedding tables exist. On an existing DB the Alembic migration
    creates them; this covers the fresh-DB `create_all` path and is idempotent.
    """
    try:
        from sqlmodel import SQLModel

        from database import engine
        from models import EmbeddingRecord, RagIndexState  # noqa: F401

        SQLModel.metadata.create_all(
            engine,
            tables=[EmbeddingRecord.__table__, RagIndexState.__table__],
        )
        if _is_postgres():
            _ensure_pgvector()
    except Exception as e:
        logger.warning("RAG init failed", extra={"extra": {"error": str(e)}})


def _ensure_pgvector() -> None:
    from sqlalchemy import text

    from database import engine

    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.execute(
            text(
                f"ALTER TABLE embeddingrecord "
                f"ADD COLUMN IF NOT EXISTS embedding_vec vector({EMBEDDING_DIM})"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_embeddingrecord_vec "
                "ON embeddingrecord USING hnsw (embedding_vec vector_cosine_ops)"
            )
        )


# ── Indexing ─────────────────────────────────────────────────────────────────


def _last_indexed_at(session, source_type: str) -> str:
    from models import RagIndexState

    row = session.get(RagIndexState, source_type)
    return row.last_indexed_at if row else "1970-01-01T00:00:00"


def _bump_state(session, source_type: str, count: int, last_at: str) -> None:
    from models import RagIndexState

    row = session.get(RagIndexState, source_type)
    if row:
        row.last_indexed_at = last_at
        row.total_count += count
    else:
        row = RagIndexState(
            source_type=source_type, last_indexed_at=last_at, total_count=count
        )
    session.add(row)


def _insert_one(
    session,
    source_type: str,
    source_id: str,
    personnel_id: str | None,
    company_id: str | None,
    chunk_text: str,
    created_at: str,
) -> bool:
    """Embed and insert one record. Returns False if source_id already exists."""
    from sqlmodel import select

    from models import EmbeddingRecord

    exists = session.exec(
        select(EmbeddingRecord.id).where(EmbeddingRecord.source_id == source_id)
    ).first()
    if exists:
        return False

    vec = embed(chunk_text)
    rec = EmbeddingRecord(
        source_type=source_type,
        source_id=source_id,
        personnel_id=personnel_id,
        company_id=company_id,
        chunk_text=chunk_text[:2000],
        embedding=vec.tobytes(),
        created_at=datetime.fromisoformat(created_at),
    )
    session.add(rec)
    session.flush()

    if _is_postgres():
        from sqlalchemy import text

        session.exec(
            text(
                "UPDATE embeddingrecord SET embedding_vec = (:v)::vector WHERE id = :id"
            ).bindparams(v=_vec_literal(vec), id=rec.id)
        )
    return True


def index_new_records() -> dict[str, int]:
    """Index at most BATCH_SIZE new records per source type. Idempotent."""
    from sqlmodel import select

    from database import get_session
    from models import AgentMemory, AgentSession, Personnel, SessionMessage, TaskRequest

    stats = {"session_message": 0, "task_result": 0, "agent_memory": 0}

    try:
        with get_session() as session:
            # ── Session messages (assistant replies only) ────────────────────
            since = _last_indexed_at(session, "session_message")
            msgs = session.exec(
                select(SessionMessage, AgentSession)
                .join(AgentSession, AgentSession.id == SessionMessage.session_id)
                .where(SessionMessage.role == "assistant")
                .where(SessionMessage.created_at > datetime.fromisoformat(since))
                .order_by(SessionMessage.created_at)
                .limit(BATCH_SIZE)
            ).all()
            last_at = since
            for msg, sess in msgs:
                text_ = (msg.content or "").strip()
                if len(text_) < 20:
                    continue
                if _insert_one(
                    session,
                    "session_message",
                    msg.id,
                    sess.personnel_id,
                    None,
                    text_,
                    msg.created_at.isoformat(),
                ):
                    stats["session_message"] += 1
                last_at = msg.created_at.isoformat()
            if msgs:
                _bump_state(
                    session, "session_message", stats["session_message"], last_at
                )

            # ── Task results ────────────────────────────────────────────────
            since = _last_indexed_at(session, "task_result")
            tasks = session.exec(
                select(TaskRequest)
                .where(TaskRequest.result.isnot(None))
                .where(TaskRequest.created_at > datetime.fromisoformat(since))
                .order_by(TaskRequest.created_at)
                .limit(BATCH_SIZE)
            ).all()
            last_at = since
            for task in tasks:
                result = (task.result or "").strip()
                if len(result) < 20:
                    continue
                if _insert_one(
                    session,
                    "task_result",
                    task.id,
                    task.assigned_agent_id,
                    task.company_id,
                    f"{task.title}\n\n{result}",
                    task.created_at.isoformat(),
                ):
                    stats["task_result"] += 1
                last_at = task.created_at.isoformat()
            if tasks:
                _bump_state(session, "task_result", stats["task_result"], last_at)

            # ── Agent memories ─────────────────────────────────────────────
            since = _last_indexed_at(session, "agent_memory")
            memories = session.exec(
                select(AgentMemory, Personnel)
                .join(Personnel, Personnel.id == AgentMemory.personnel_id)
                .where(AgentMemory.created_at > datetime.fromisoformat(since))
                .order_by(AgentMemory.created_at)
                .limit(BATCH_SIZE)
            ).all()
            last_at = since
            for mem, person in memories:
                text_ = (mem.summary or "").strip()
                if len(text_) < 20:
                    continue
                if _insert_one(
                    session,
                    "agent_memory",
                    mem.id,
                    mem.personnel_id,
                    person.company_id,
                    text_,
                    mem.created_at.isoformat(),
                ):
                    stats["agent_memory"] += 1
                last_at = mem.created_at.isoformat()
            if memories:
                _bump_state(session, "agent_memory", stats["agent_memory"], last_at)

            session.commit()
    except Exception as e:
        logger.warning("RAG indexing error", extra={"extra": {"error": str(e)}})

    total = sum(stats.values())
    if total:
        logger.info("RAG index updated", extra={"extra": {**stats, "total": total}})
    return stats


# ── Search ───────────────────────────────────────────────────────────────────


def _search_pg(session, q_vec: np.ndarray, company_id, personnel_id, k: int):
    from sqlalchemy import text

    clauses = ["embedding_vec IS NOT NULL"]
    params = {"q": _vec_literal(q_vec), "k": k}
    if company_id:
        clauses.append("(company_id = :cid OR company_id IS NULL)")
        params["cid"] = company_id
    if personnel_id:
        clauses.append("personnel_id = :pid")
        params["pid"] = personnel_id
    sql = (
        "SELECT source_type, source_id, chunk_text, created_at, "
        "1 - (embedding_vec <=> (:q)::vector) AS score "
        f"FROM embeddingrecord WHERE {' AND '.join(clauses)} "
        "ORDER BY embedding_vec <=> (:q)::vector LIMIT :k"
    )
    return session.exec(text(sql).bindparams(**params)).all()


def _search_bruteforce(session, q_vec: np.ndarray, company_id, personnel_id, k: int):
    from sqlmodel import select

    from models import EmbeddingRecord

    q = select(EmbeddingRecord)
    if company_id:
        q = q.where(
            (EmbeddingRecord.company_id == company_id)
            | (EmbeddingRecord.company_id.is_(None))
        )
    if personnel_id:
        q = q.where(EmbeddingRecord.personnel_id == personnel_id)
    rows = session.exec(q).all()
    if not rows:
        return []

    mat = np.frombuffer(b"".join(r.embedding for r in rows), dtype=np.float32).reshape(
        len(rows), EMBEDDING_DIM
    )
    scores = mat @ q_vec  # both normalised → cosine similarity
    order = np.argsort(-scores)[:k]
    return [
        (
            rows[i].source_type,
            rows[i].source_id,
            rows[i].chunk_text,
            rows[i].created_at.isoformat(),
            float(scores[i]),
        )
        for i in order
    ]


def search(
    query: str,
    company_id: str | None = None,
    personnel_id: str | None = None,
    k: int = TOP_K_DEFAULT,
) -> list[dict]:
    """
    Top-k semantically similar records. Returns [] on cold start
    (< MIN_RECORDS_FOR_SEARCH indexed) or any error (never raises).
    """
    try:
        from sqlmodel import func, select

        from database import get_session
        from models import EmbeddingRecord

        with get_session() as session:
            total = session.exec(
                select(func.count()).select_from(EmbeddingRecord)
            ).one()
            if total < MIN_RECORDS_FOR_SEARCH:
                return []

            q_vec = embed(query)
            if _is_postgres():
                rows = _search_pg(session, q_vec, company_id, personnel_id, k)
            else:
                rows = _search_bruteforce(session, q_vec, company_id, personnel_id, k)

        return [
            {
                "source_type": r[0],
                "source_id": r[1],
                "chunk_text": r[2],
                "created_at": r[3],
                "score": round(float(r[4]), 4),
            }
            for r in rows
        ]
    except Exception as e:
        logger.warning("RAG search error", extra={"extra": {"error": str(e)}})
        return []


def get_stats() -> dict:
    try:
        from sqlmodel import func, select

        from database import get_session
        from models import EmbeddingRecord, RagIndexState

        with get_session() as session:
            total = session.exec(
                select(func.count()).select_from(EmbeddingRecord)
            ).one()
            by_type_rows = session.exec(
                select(EmbeddingRecord.source_type, func.count()).group_by(
                    EmbeddingRecord.source_type
                )
            ).all()
            states = session.exec(select(RagIndexState)).all()
        return {
            "total": total,
            "ready": total >= MIN_RECORDS_FOR_SEARCH,
            "by_type": {st: cnt for st, cnt in by_type_rows},
            "index_state": {
                s.source_type: {
                    "last_indexed_at": s.last_indexed_at,
                    "total_count": s.total_count,
                }
                for s in states
            },
        }
    except Exception:
        return {"total": 0, "ready": False, "by_type": {}, "index_state": {}}
