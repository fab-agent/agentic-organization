"""a person's consent to share a training-need signal with their manager (ADR-0021)

Revision ID: f8c4e1b73a26
Revises: e7b3d9a25c48
Create Date: 2026-09-30 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = "f8c4e1b73a26"
down_revision: str | Sequence[str] | None = "e7b3d9a25c48"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "worktrainingshare",
        sa.Column("id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("company_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("personnel_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("criterion_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("criterion_hash", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("shared_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "personnel_id",
            "criterion_id",
            "criterion_hash",
            name="uq_worktrainingshare",
        ),
    )
    op.create_index(
        "ix_worktrainingshare_company_id", "worktrainingshare", ["company_id"]
    )
    op.create_index(
        "ix_worktrainingshare_personnel_id", "worktrainingshare", ["personnel_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_worktrainingshare_personnel_id", table_name="worktrainingshare")
    op.drop_index("ix_worktrainingshare_company_id", table_name="worktrainingshare")
    op.drop_table("worktrainingshare")
