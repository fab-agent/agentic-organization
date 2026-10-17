"""stored run diagnosis (ADR-0023)

Revision ID: a9d2c6e4b710
Revises: f8c4e1b73a26
Create Date: 2026-10-17 21:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = "a9d2c6e4b710"
down_revision: str | Sequence[str] | None = "f8c4e1b73a26"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "rundiagnosis",
        sa.Column("company_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("persona_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("run_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("suspect_layer", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("scores_json", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("findings_json", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("events_seen", sa.Integer(), nullable=False),
        sa.Column("ignored_client_claims", sa.Integer(), nullable=False),
        sa.Column("invalid_events", sa.Integer(), nullable=False),
        sa.Column("truncated", sa.Boolean(), nullable=False),
        sa.Column("diagnoser_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["company.id"]),
        sa.PrimaryKeyConstraint("company_id", "persona_id", "run_id"),
    )


def downgrade() -> None:
    op.drop_table("rundiagnosis")
