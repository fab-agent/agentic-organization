import os
from collections.abc import Generator
from contextlib import contextmanager

from sqlmodel import Session, SQLModel, create_engine

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./data/app.db")

# `check_same_thread` is a SQLite-only pysqlite arg; PostgreSQL/MySQL reject it.
_connect_args = (
    {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
)
_engine_kwargs: dict = {"echo": False, "connect_args": _connect_args}
if not DATABASE_URL.startswith("sqlite"):
    # Recycle connections so a long-idle pooled connection doesn't hand back a
    # dead socket (common behind PgBouncer / cloud Postgres).
    _engine_kwargs["pool_pre_ping"] = True
    _engine_kwargs["pool_recycle"] = 1800

engine = create_engine(DATABASE_URL, **_engine_kwargs)


def _is_fresh_db() -> bool:
    """Return True if the database has no alembic_version table (brand-new install)."""
    from sqlalchemy import inspect

    try:
        return not inspect(engine).has_table("alembic_version")
    except Exception:
        return True


def init_db() -> None:
    os.makedirs("data", exist_ok=True)

    from alembic import command
    from alembic.config import Config

    ini_path = os.path.join(os.path.dirname(__file__), "alembic.ini")
    alembic_cfg = Config(ini_path)

    if _is_fresh_db():
        # Brand-new database: create all tables directly from SQLModel metadata,
        # then stamp alembic_version to the current head so incremental migrations
        # don't try to add columns to tables that already have them.
        import models  # noqa: F401 — ensure all SQLModel tables are registered

        SQLModel.metadata.create_all(engine)
        command.stamp(alembic_cfg, "head")
    else:
        # Existing database: run only the incremental migrations that are missing.
        command.upgrade(alembic_cfg, "head")
        # Also create any new SQLModel tables not yet covered by Alembic migrations.
        # create_all uses IF NOT EXISTS so it's safe to call on existing databases.
        import models  # noqa: F401 — registers all SQLModel tables in metadata

        SQLModel.metadata.create_all(engine)


@contextmanager
def get_session() -> Generator[Session, None, None]:
    with Session(engine, expire_on_commit=False) as session:
        yield session
