"""one active harness version per logical key

Databases that already ran f4c8d2a6b715 before the partial unique index was added to
it get the index here; databases created after it already have it.

Revision ID: a1d5e7c3b926
Revises: f4c8d2a6b715
Create Date: 2026-10-18 21:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a1d5e7c3b926"
down_revision: str | Sequence[str] | None = "f4c8d2a6b715"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NAME = "uq_harness_one_active"


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if "harnessartifact" not in insp.get_table_names():
        return
    if _NAME in {i["name"] for i in insp.get_indexes("harnessartifact")}:
        return
    # Two rows already active for one key (only possible through the race this index
    # closes) keep the newest active and supersede the rest, so the index can be built.
    op.execute(
        sa.text(
            "UPDATE harnessartifact SET status = 'superseded' WHERE status = 'active' "
            "AND EXISTS (SELECT 1 FROM harnessartifact o WHERE o.status = 'active' "
            "AND o.company_id = harnessartifact.company_id "
            "AND o.level = harnessartifact.level "
            "AND o.target_id = harnessartifact.target_id "
            "AND o.kind = harnessartifact.kind AND o.key = harnessartifact.key "
            "AND o.version > harnessartifact.version)"
        )
    )
    op.create_index(
        _NAME,
        "harnessartifact",
        ["company_id", "level", "target_id", "kind", "key"],
        unique=True,
        sqlite_where=sa.text("status = 'active'"),
        postgresql_where=sa.text("status = 'active'"),
    )


def downgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if "harnessartifact" in insp.get_table_names() and _NAME in {
        i["name"] for i in insp.get_indexes("harnessartifact")
    }:
        op.drop_index(_NAME, table_name="harnessartifact")
