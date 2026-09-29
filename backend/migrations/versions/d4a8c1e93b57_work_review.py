"""work review signals and notes (ADR-0019 §6)

Revision ID: d4a8c1e93b57
Revises: c9e5a3b72d14
Create Date: 2026-09-29 18:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = "d4a8c1e93b57"
down_revision: str | Sequence[str] | None = "c9e5a3b72d14"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "worksignal",
        sa.Column("personnel_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("day", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("kind", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("value", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("company_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("personnel_id", "day", "kind", "value"),
    )
    op.create_index("ix_worksignal_company_id", "worksignal", ["company_id"])
    op.create_table(
        "worknote",
        sa.Column("id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("personnel_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("company_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("day", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("text", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_worknote_personnel_id", "worknote", ["personnel_id"])
    op.create_index("ix_worknote_company_id", "worknote", ["company_id"])


def downgrade() -> None:
    op.drop_index("ix_worknote_company_id", table_name="worknote")
    op.drop_index("ix_worknote_personnel_id", table_name="worknote")
    op.drop_table("worknote")
    op.drop_index("ix_worksignal_company_id", table_name="worksignal")
    op.drop_table("worksignal")
