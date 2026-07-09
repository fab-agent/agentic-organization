"""
External database connection service.

Supports: SQLite, PostgreSQL, MySQL/MariaDB (via SQLAlchemy).
Provides:
  - Schema discovery (tables, columns, types, row counts)
  - Semantic annotation storage/retrieval
  - Safe SELECT-only query execution
"""
import json
import re
from typing import Any

from sqlalchemy import create_engine, text, inspect


def _engine(dsn: str, db_type: str):
    # Enforce correct scheme prefix
    if db_type == "sqlite" and not dsn.startswith("sqlite"):
        dsn = f"sqlite:///{dsn}"
    connect_args = {}
    if db_type == "sqlite":
        connect_args["check_same_thread"] = False
    return create_engine(dsn, connect_args=connect_args, pool_pre_ping=True)


def test_connection(dsn: str, db_type: str) -> tuple[bool, str]:
    """Returns (ok, error_message)."""
    try:
        engine = _engine(dsn, db_type)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        engine.dispose()
        return True, ""
    except Exception as e:
        return False, str(e)


def discover_schema(dsn: str, db_type: str) -> dict:
    """
    Inspect the database and return a schema dict:
    {
      "tables": {
        "table_name": {
          "description": "",       # filled by user later
          "row_count": 1234,
          "columns": {
            "col_name": {
              "type": "VARCHAR",
              "nullable": true,
              "primary_key": false,
              "foreign_key": null,   # "other_table.other_col" or null
              "description": ""      # filled by user later
            }
          }
        }
      }
    }
    """
    engine = _engine(dsn, db_type)
    insp = inspect(engine)
    tables: dict[str, Any] = {}

    for table_name in insp.get_table_names():
        columns: dict[str, Any] = {}

        # Build FK map: col_name -> "ref_table.ref_col"
        fk_map: dict[str, str] = {}
        for fk in insp.get_foreign_keys(table_name):
            for lc, rc in zip(fk["constrained_columns"], fk["referred_columns"]):
                fk_map[lc] = f"{fk['referred_table']}.{rc}"

        pk_cols = set(insp.get_pk_constraint(table_name).get("constrained_columns", []))

        for col in insp.get_columns(table_name):
            cname = col["name"]
            columns[cname] = {
                "type": str(col["type"]),
                "nullable": col.get("nullable", True),
                "primary_key": cname in pk_cols,
                "foreign_key": fk_map.get(cname),
                "description": "",
            }

        # Row count (best-effort)
        row_count = 0
        try:
            with engine.connect() as conn:
                row_count = conn.execute(text(f'SELECT COUNT(*) FROM "{table_name}"')).scalar() or 0
        except Exception:
            pass

        tables[table_name] = {
            "description": "",
            "row_count": row_count,
            "columns": columns,
        }

    engine.dispose()
    return {"tables": tables}


def execute_query(dsn: str, db_type: str, sql: str, limit: int = 200) -> dict:
    """
    Execute a SELECT query and return results.
    Raises ValueError if non-SELECT statement is detected.
    Returns: {"columns": [...], "rows": [[...], ...], "row_count": n}
    """
    _assert_select_only(sql)

    # Wrap in row limit if not already present
    wrapped = _apply_limit(sql, limit)

    engine = _engine(dsn, db_type)
    try:
        with engine.connect() as conn:
            result = conn.execute(text(wrapped))
            columns = list(result.keys())
            rows = [list(row) for row in result.fetchall()]
        return {"columns": columns, "rows": rows, "row_count": len(rows)}
    finally:
        engine.dispose()


def build_schema_context(schema_json: str, examples_json: str | None = None) -> str:
    """
    Build a concise text description of the database schema for injection
    into an LLM tool description or system prompt.
    """
    try:
        schema = json.loads(schema_json)
    except Exception:
        return ""

    lines = ["## Database Schema\n"]
    for tname, tdata in schema.get("tables", {}).items():
        tdesc = tdata.get("description", "")
        row_count = tdata.get("row_count", 0)
        lines.append(f"### `{tname}`" + (f" — {tdesc}" if tdesc else "") + f" ({row_count:,} rows)")

        for cname, cdata in tdata.get("columns", {}).items():
            flags = []
            if cdata.get("primary_key"):
                flags.append("PK")
            if cdata.get("foreign_key"):
                flags.append(f"FK→{cdata['foreign_key']}")
            if not cdata.get("nullable", True):
                flags.append("NOT NULL")
            flag_str = f" [{', '.join(flags)}]" if flags else ""
            cdesc = cdata.get("description", "")
            lines.append(f"  - `{cname}` {cdata.get('type', '')} {flag_str}" + (f" — {cdesc}" if cdesc else ""))

        lines.append("")

    if examples_json:
        try:
            examples = json.loads(examples_json)
            if examples:
                lines.append("## Example Queries\n")
                for ex in examples[:5]:
                    if ex.get("description"):
                        lines.append(f"-- {ex['description']}")
                    lines.append(ex.get("sql", "") + "\n")
        except Exception:
            pass

    return "\n".join(lines)


# ── Safety ────────────────────────────────────────────────────────────────────

_FORBIDDEN = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|CREATE|ALTER|TRUNCATE|REPLACE|EXEC|EXECUTE|GRANT|REVOKE)\b",
    re.IGNORECASE,
)

def _assert_select_only(sql: str) -> None:
    stripped = sql.strip()
    if not stripped.upper().startswith("SELECT") and not stripped.upper().startswith("WITH"):
        raise ValueError("Only SELECT (and CTE WITH ... SELECT) queries are allowed.")
    if _FORBIDDEN.search(stripped):
        raise ValueError("Query contains forbidden keyword.")


def _apply_limit(sql: str, limit: int) -> str:
    """Append LIMIT if no LIMIT/FETCH clause present."""
    upper = sql.upper()
    if "LIMIT" in upper or "FETCH" in upper:
        return sql
    return f"{sql.rstrip(';')} LIMIT {limit}"
