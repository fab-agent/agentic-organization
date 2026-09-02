"""audit_severity

Revision ID: a4e6c8b02d17
Revises: f2b8d1e4c690
Create Date: 2026-09-02 10:15:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = "a4e6c8b02d17"
down_revision: str | Sequence[str] | None = "f2b8d1e4c690"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "auditseverity",
        sa.Column("chain_key", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("company_id", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("severity", sa.Integer(), nullable=False),
        sa.Column("category", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("reason", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("alerted", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("chain_key", "seq"),
    )
    op.create_index("ix_auditseverity_company_id", "auditseverity", ["company_id"])


def downgrade() -> None:
    op.drop_index("ix_auditseverity_company_id", table_name="auditseverity")
    op.drop_table("auditseverity")
