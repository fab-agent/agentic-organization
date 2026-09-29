"""work ratings: fit verdicts per run and rubric criterion (ADR-0021)

Revision ID: e7b3d9a25c48
Revises: d4a8c1e93b57
Create Date: 2026-09-29 21:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = "e7b3d9a25c48"
down_revision: str | Sequence[str] | None = "d4a8c1e93b57"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workrating",
        sa.Column("id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("company_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("personnel_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("day", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("run_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("criterion_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("criterion_hash", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("rubric_version", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column(
            "criterion_status", sqlmodel.sql.sqltypes.AutoString(), nullable=False
        ),
        sa.Column("verdict", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("probability", sa.Float(), nullable=True),
        sa.Column("model", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("contest_note", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("contested_at", sa.DateTime(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "personnel_id",
            "run_id",
            "criterion_id",
            "criterion_hash",
            name="uq_workrating_run_criterion",
        ),
    )
    op.create_index("ix_workrating_company_id", "workrating", ["company_id"])
    op.create_index("ix_workrating_personnel_id", "workrating", ["personnel_id"])


def downgrade() -> None:
    op.drop_index("ix_workrating_personnel_id", table_name="workrating")
    op.drop_index("ix_workrating_company_id", table_name="workrating")
    op.drop_table("workrating")
