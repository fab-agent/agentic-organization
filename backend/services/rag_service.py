"""
RAG service — local multilingual embeddings + sqlite-vec.

Design decisions:
  - Separate DB (data/rag.db) — never touches main app.db, no migrations needed
  - Model: paraphrase-multilingual-MiniLM-L12-v2 (384-dim, TR+EN, ~80MB, CPU-friendly)
  - Singleton model: loaded on first call, stays in RAM for the process lifetime
  - Incremental indexing: tracks last_indexed_at per source type, max 200 records/run
  - Cold start guard: search returns [] until MIN_RECORDS records are indexed
  - Sources: SessionMessage (assistant), TaskRequest (result), AgentMemory (summary)
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime
from pathlib import Path

import numpy as np

logger = logging.getLogger("app")

# ── Config ────────────────────────────────────────────────────────────────────

MODEL_NAME = "paraphrase-multilingual-MiniLM-L12-v2"
EMBEDDING_DIM = 384
RAG_DB_PATH = Path(__file__).parent.parent / "data" / "rag.db"
BATCH_SIZE = 200
MIN_RECORDS_FOR_SEARCH = 20
TOP_K_DEFAULT = 5

# ── Singleton model ───────────────────────────────────────────────────────────

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


# ── DB connection ─────────────────────────────────────────────────────────────


def _conn() -> sqlite3.Connection:
    import sqlite_vec

    c = sqlite3.connect(str(RAG_DB_PATH))
    c.enable_load_extension(True)
    sqlite_vec.load(c)
    c.enable_load_extension(False)
    c.row_factory = sqlite3.Row
    return c


def init_rag_db() -> None:
    RAG_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _conn() as c:
        c.executescript(f"""
            CREATE VIRTUAL TABLE IF NOT EXISTS vec_embeddings
                USING vec0(embedding float[{EMBEDDING_DIM}]);

            CREATE TABLE IF NOT EXISTS embedding_meta (
                rowid        INTEGER PRIMARY KEY,
                source_type  TEXT NOT NULL,
                source_id    TEXT NOT NULL UNIQUE,
                personnel_id TEXT,
                company_id   TEXT,
                chunk_text   TEXT NOT NULL,
                created_at   TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_meta_company    ON embedding_meta(company_id);
            CREATE INDEX IF NOT EXISTS idx_meta_personnel  ON embedding_meta(personnel_id);
            CREATE INDEX IF NOT EXISTS idx_meta_source_id  ON embedding_meta(source_id);

            CREATE TABLE IF NOT EXISTS index_state (
                source_type     TEXT PRIMARY KEY,
                last_indexed_at TEXT NOT NULL DEFAULT '1970-01-01T00:00:00',
                total_count     INTEGER NOT NULL DEFAULT 0
            );
        """)


# ── Indexing helpers ──────────────────────────────────────────────────────────


def _last_indexed_at(c: sqlite3.Connection, source_type: str) -> str:
    row = c.execute(
        "SELECT last_indexed_at FROM index_state WHERE source_type = ?", (source_type,)
    ).fetchone()
    return row["last_indexed_at"] if row else "1970-01-01T00:00:00"


def _bump_state(
    c: sqlite3.Connection, source_type: str, count: int, last_at: str
) -> None:
    c.execute(
        """INSERT INTO index_state (source_type, last_indexed_at, total_count) VALUES (?,?,?)
           ON CONFLICT(source_type) DO UPDATE SET
               last_indexed_at = excluded.last_indexed_at,
               total_count = total_count + excluded.total_count""",
        (source_type, last_at, count),
    )


def _insert_one(
    c: sqlite3.Connection,
    source_type: str,
    source_id: str,
    personnel_id: str | None,
    company_id: str | None,
    chunk_text: str,
    created_at: str,
) -> bool:
    """Embed and insert one record. Returns False if source_id already exists."""
    if c.execute(
        "SELECT 1 FROM embedding_meta WHERE source_id = ?", (source_id,)
    ).fetchone():
        return False
    vec = embed(chunk_text)
    cur = c.execute(
        """INSERT INTO embedding_meta
               (source_type, source_id, personnel_id, company_id, chunk_text, created_at)
           VALUES (?,?,?,?,?,?)""",
        (
            source_type,
            source_id,
            personnel_id,
            company_id,
            chunk_text[:2000],
            created_at,
        ),
    )
    c.execute(
        "INSERT INTO vec_embeddings (rowid, embedding) VALUES (?,?)",
        (cur.lastrowid, vec.tobytes()),
    )
    return True


# ── Public: incremental indexer ───────────────────────────────────────────────


def index_new_records() -> dict[str, int]:
    """
    Index at most BATCH_SIZE new records per source type.
    Safe to call repeatedly — skips already-indexed records via source_id uniqueness.
    """
    from sqlmodel import select

    from database import get_session
    from models import AgentMemory, AgentSession, Personnel, SessionMessage, TaskRequest

    stats: dict[str, int] = {"session_message": 0, "task_result": 0, "agent_memory": 0}

    try:
        with _conn() as rag:
            with get_session() as app:
                # ── Session messages (assistant replies only) ──────────────
                since = _last_indexed_at(rag, "session_message")
                msgs = app.exec(
                    select(SessionMessage, AgentSession)
                    .join(AgentSession, AgentSession.id == SessionMessage.session_id)
                    .where(SessionMessage.role == "assistant")
                    .where(SessionMessage.created_at > datetime.fromisoformat(since))
                    .order_by(SessionMessage.created_at)
                    .limit(BATCH_SIZE)
                ).all()
                last_msg_at = since
                for msg, sess in msgs:
                    text = (msg.content or "").strip()
                    if len(text) < 20:
                        continue
                    if _insert_one(
                        rag,
                        "session_message",
                        msg.id,
                        sess.personnel_id,
                        None,
                        text,
                        msg.created_at.isoformat(),
                    ):
                        stats["session_message"] += 1
                    last_msg_at = msg.created_at.isoformat()
                if msgs:
                    _bump_state(
                        rag, "session_message", stats["session_message"], last_msg_at
                    )

                # ── Task results ───────────────────────────────────────────
                since = _last_indexed_at(rag, "task_result")
                tasks = app.exec(
                    select(TaskRequest)
                    .where(TaskRequest.result.isnot(None))
                    .where(TaskRequest.created_at > datetime.fromisoformat(since))
                    .order_by(TaskRequest.created_at)
                    .limit(BATCH_SIZE)
                ).all()
                last_task_at = since
                for task in tasks:
                    result = (task.result or "").strip()
                    if len(result) < 20:
                        continue
                    chunk = f"{task.title}\n\n{result}"
                    if _insert_one(
                        rag,
                        "task_result",
                        task.id,
                        task.assigned_agent_id,
                        task.company_id,
                        chunk,
                        task.created_at.isoformat(),
                    ):
                        stats["task_result"] += 1
                    last_task_at = task.created_at.isoformat()
                if tasks:
                    _bump_state(rag, "task_result", stats["task_result"], last_task_at)

                # ── Agent memories ─────────────────────────────────────────
                since = _last_indexed_at(rag, "agent_memory")
                memories = app.exec(
                    select(AgentMemory, Personnel)
                    .join(Personnel, Personnel.id == AgentMemory.personnel_id)
                    .where(AgentMemory.created_at > datetime.fromisoformat(since))
                    .order_by(AgentMemory.created_at)
                    .limit(BATCH_SIZE)
                ).all()
                last_mem_at = since
                for mem, person in memories:
                    text = (mem.summary or "").strip()
                    if len(text) < 20:
                        continue
                    if _insert_one(
                        rag,
                        "agent_memory",
                        mem.id,
                        mem.personnel_id,
                        person.company_id,
                        text,
                        mem.created_at.isoformat(),
                    ):
                        stats["agent_memory"] += 1
                    last_mem_at = mem.created_at.isoformat()
                if memories:
                    _bump_state(rag, "agent_memory", stats["agent_memory"], last_mem_at)

                rag.commit()

    except Exception as e:
        logger.warning("RAG indexing error", extra={"extra": {"error": str(e)}})

    total = sum(stats.values())
    if total:
        logger.info("RAG index updated", extra={"extra": {**stats, "total": total}})
    return stats


# ── Public: semantic search ───────────────────────────────────────────────────


def search(
    query: str,
    company_id: str | None = None,
    personnel_id: str | None = None,
    k: int = TOP_K_DEFAULT,
) -> list[dict]:
    """
    Return top-k semantically similar records.
    Empty list returned when:
      - fewer than MIN_RECORDS records indexed (cold start)
      - any error (never raises)
    """
    try:
        with _conn() as c:
            total = c.execute("SELECT COUNT(*) FROM embedding_meta").fetchone()[0]
            if total < MIN_RECORDS_FOR_SEARCH:
                return []

            q_vec = embed(query)

            # Step 1: broad KNN from vector table (over-fetch to allow post-filter)
            candidates = c.execute(
                "SELECT rowid, distance FROM vec_embeddings WHERE embedding MATCH ? AND k = ?",
                (q_vec.tobytes(), k * 4),
            ).fetchall()

            if not candidates:
                return []

            rowid_to_dist = {r["rowid"]: r["distance"] for r in candidates}
            rowids = list(rowid_to_dist.keys())
            placeholders = ",".join("?" * len(rowids))

            # Step 2: fetch metadata with optional filters
            filter_clauses, filter_params = [], list(rowids)
            if company_id:
                filter_clauses.append("(company_id = ? OR company_id IS NULL)")
                filter_params.append(company_id)
            if personnel_id:
                filter_clauses.append("personnel_id = ?")
                filter_params.append(personnel_id)

            where = ""
            if filter_clauses:
                where = " AND " + " AND ".join(filter_clauses)

            rows = c.execute(
                f"SELECT rowid, source_type, source_id, chunk_text, created_at "
                f"FROM embedding_meta WHERE rowid IN ({placeholders}){where}",
                filter_params,
            ).fetchall()

            # Step 3: sort by similarity distance, take top k
            sorted_rows = sorted(rows, key=lambda r: rowid_to_dist[r["rowid"]])[:k]

            return [
                {
                    "source_type": r["source_type"],
                    "source_id": r["source_id"],
                    "chunk_text": r["chunk_text"],
                    "created_at": r["created_at"],
                    "score": round(1 - rowid_to_dist[r["rowid"]], 4),
                }
                for r in sorted_rows
            ]

    except Exception as e:
        logger.warning("RAG search error", extra={"extra": {"error": str(e)}})
        return []


# ── Public: index stats ───────────────────────────────────────────────────────


def get_stats() -> dict:
    try:
        with _conn() as c:
            total = c.execute("SELECT COUNT(*) FROM embedding_meta").fetchone()[0]
            by_type = c.execute(
                "SELECT source_type, COUNT(*) as cnt FROM embedding_meta GROUP BY source_type"
            ).fetchall()
            states = c.execute(
                "SELECT source_type, last_indexed_at, total_count FROM index_state"
            ).fetchall()
            return {
                "total": total,
                "ready": total >= MIN_RECORDS_FOR_SEARCH,
                "by_type": {r["source_type"]: r["cnt"] for r in by_type},
                "index_state": {
                    r["source_type"]: {
                        "last_indexed_at": r["last_indexed_at"],
                        "total_count": r["total_count"],
                    }
                    for r in states
                },
            }
    except Exception:
        return {"total": 0, "ready": False, "by_type": {}, "index_state": {}}
