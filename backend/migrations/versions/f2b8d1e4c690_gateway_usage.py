"""gateway_usage

Revision ID: f2b8d1e4c690
Revises: e1a4c7d92f38
Create Date: 2026-09-02 09:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = "f2b8d1e4c690"
down_revision: str | Sequence[str] | None = "e1a4c7d92f38"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "gatewayusage",
        sa.Column("persona_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("period", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("company_id", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("requests", sa.Integer(), nullable=False),
        sa.Column("tokens_in", sa.Integer(), nullable=False),
        sa.Column("tokens_out", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("persona_id", "period"),
    )
    op.create_index("ix_gatewayusage_company_id", "gatewayusage", ["company_id"])


def downgrade() -> None:
    op.drop_index("ix_gatewayusage_company_id", table_name="gatewayusage")
    op.drop_table("gatewayusage")
