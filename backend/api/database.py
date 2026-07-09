"""Database connection management — CRUD, schema discovery, semantic annotations, query."""
import json
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import select

from api.auth import get_current_user, require_manager
from core.security import decrypt, encrypt
from database import get_session
from models import DatabaseConnection, User
from services.database_service import (
    build_schema_context,
    discover_schema,
    execute_query,
    test_connection,
)

logger = logging.getLogger("app")
router = APIRouter(prefix="/databases", tags=["databases"])


# ── Schemas ───────────────────────────────────────────────────────────────────

class DBCreate(BaseModel):
    name: str
    db_type: str          # "sqlite" | "postgresql" | "mysql"
    dsn: str              # plain connection string
    company_id: Optional[str] = None


class DBAnnotate(BaseModel):
    """Partial update: set semantic descriptions on tables/columns + example queries."""
    schema_json: Optional[str] = None    # full annotated schema JSON
    examples_json: Optional[str] = None  # [{sql, description}]


class QueryRequest(BaseModel):
    db_id: str
    sql: str
    limit: int = 200


class DBResponse(BaseModel):
    id: str
    name: str
    db_type: str
    company_id: Optional[str]
    status: str
    last_checked: Optional[str]
    schema: Optional[dict] = None
    examples: Optional[list] = None
    created_at: str


def _to_resp(row: DatabaseConnection, include_schema: bool = False) -> DBResponse:
    schema = None
    examples = None
    if include_schema and row.schema_json:
        try:
            schema = json.loads(row.schema_json)
        except Exception:
            pass
    if include_schema and row.examples_json:
        try:
            examples = json.loads(row.examples_json)
        except Exception:
            pass
    return DBResponse(
        id=row.id,
        name=row.name,
        db_type=row.db_type,
        company_id=row.company_id,
        status=row.status,
        last_checked=row.last_checked.isoformat() if row.last_checked else None,
        schema=schema,
        examples=examples,
        created_at=row.created_at.isoformat(),
    )


# ── CRUD ──────────────────────────────────────────────────────────────────────

@router.get("/")
def list_databases(
    company_id: Optional[str] = None,
    _: User = Depends(get_current_user),
) -> list[DBResponse]:
    with get_session() as session:
        q = select(DatabaseConnection)
        if company_id:
            q = q.where(DatabaseConnection.company_id == company_id)
        rows = session.exec(q.order_by(DatabaseConnection.created_at.desc())).all()
        return [_to_resp(r) for r in rows]


@router.get("/{db_id}")
def get_database(db_id: str, _: User = Depends(get_current_user)) -> DBResponse:
    with get_session() as session:
        row = session.get(DatabaseConnection, db_id)
        if not row:
            raise HTTPException(status_code=404, detail="Database not found")
        return _to_resp(row, include_schema=True)


@router.post("/", status_code=201)
def create_database(body: DBCreate, _: User = Depends(require_manager)) -> DBResponse:
    if body.db_type not in ("sqlite", "postgresql", "mysql"):
        raise HTTPException(status_code=422, detail="db_type must be sqlite, postgresql, or mysql")

    ok, err = test_connection(body.dsn, body.db_type)
    with get_session() as session:
        row = DatabaseConnection(
            name=body.name,
            db_type=body.db_type,
            encrypted_dsn=encrypt(body.dsn),
            company_id=body.company_id,
            status="ok" if ok else "error",
            last_checked=datetime.now(timezone.utc),
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        logger.info("Database connection created", extra={"extra": {
            "id": row.id, "type": body.db_type, "ok": ok
        }})
        if not ok:
            logger.warning("DB connection failed", extra={"extra": {"error": err}})
        return _to_resp(row)


@router.delete("/{db_id}", status_code=204)
def delete_database(db_id: str, _: User = Depends(require_manager)):
    with get_session() as session:
        row = session.get(DatabaseConnection, db_id)
        if not row:
            raise HTTPException(status_code=404, detail="Database not found")
        session.delete(row)
        session.commit()


# ── Schema discovery ───────────────────────────────────────────────────────────

@router.post("/{db_id}/discover")
def discover(db_id: str, _: User = Depends(require_manager)) -> DBResponse:
    """Auto-discover schema from the live database, preserve existing annotations."""
    with get_session() as session:
        row = session.get(DatabaseConnection, db_id)
        if not row:
            raise HTTPException(status_code=404, detail="Database not found")

        dsn = decrypt(row.encrypted_dsn)
        try:
            fresh = discover_schema(dsn, row.db_type)
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Schema discovery failed: {e}")

        # Merge: preserve existing user descriptions, add new tables/columns
        if row.schema_json:
            try:
                existing = json.loads(row.schema_json)
                for tname, tdata in fresh["tables"].items():
                    if tname in existing.get("tables", {}):
                        ex_t = existing["tables"][tname]
                        tdata["description"] = ex_t.get("description", "")
                        for cname, cdata in tdata["columns"].items():
                            if cname in ex_t.get("columns", {}):
                                cdata["description"] = ex_t["columns"][cname].get("description", "")
            except Exception:
                pass

        row.schema_json = json.dumps(fresh, ensure_ascii=False)
        row.status = "ok"
        row.last_checked = datetime.now(timezone.utc)
        session.add(row)
        session.commit()
        session.refresh(row)
        return _to_resp(row, include_schema=True)


# ── Semantic annotations ───────────────────────────────────────────────────────

@router.patch("/{db_id}/annotate")
def annotate(db_id: str, body: DBAnnotate, _: User = Depends(require_manager)) -> DBResponse:
    """Save user-provided semantic descriptions and example queries."""
    with get_session() as session:
        row = session.get(DatabaseConnection, db_id)
        if not row:
            raise HTTPException(status_code=404, detail="Database not found")
        if body.schema_json is not None:
            row.schema_json = body.schema_json
        if body.examples_json is not None:
            row.examples_json = body.examples_json
        session.add(row)
        session.commit()
        session.refresh(row)
        return _to_resp(row, include_schema=True)


# ── Query ─────────────────────────────────────────────────────────────────────

@router.post("/query")
def query(body: QueryRequest, _: User = Depends(get_current_user)) -> dict:
    """Execute a SELECT query against a configured database."""
    with get_session() as session:
        row = session.get(DatabaseConnection, body.db_id)
        if not row:
            raise HTTPException(status_code=404, detail="Database not found")
        dsn = decrypt(row.encrypted_dsn)

    try:
        result = execute_query(dsn, row.db_type, body.sql, limit=min(body.limit, 500))
        logger.info("DB query executed", extra={"extra": {
            "db_id": body.db_id, "rows": result["row_count"]
        }})
        return result
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.error("DB query failed", extra={"extra": {"error": str(e)}})
        raise HTTPException(status_code=502, detail=f"Query failed: {e}")


# ── Schema context (for agent tool injection) ──────────────────────────────────

@router.get("/{db_id}/context")
def schema_context(db_id: str, _: User = Depends(get_current_user)) -> dict:
    """Return the schema as a formatted text context for LLM injection."""
    with get_session() as session:
        row = session.get(DatabaseConnection, db_id)
        if not row:
            raise HTTPException(status_code=404, detail="Database not found")
        ctx = build_schema_context(row.schema_json or "{}", row.examples_json)
        return {"context": ctx, "db_id": db_id, "name": row.name}
