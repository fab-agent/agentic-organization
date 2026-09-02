"""persona heartbeat (ADR-0009)

Revision ID: c8e2f04b1d37
Revises: b7d1e93a4c25
Create Date: 2026-09-03 06:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = "c8e2f04b1d37"
down_revision: str | Sequence[str] | None = "b7d1e93a4c25"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "personaheartbeat",
        sa.Column("persona_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("company_id", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("last_seen", sa.DateTime(), nullable=False),
        sa.Column("session_ref", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("sandbox_digest", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column(
            "opencode_version", sqlmodel.sql.sqltypes.AutoString(), nullable=True
        ),
        sa.PrimaryKeyConstraint("persona_id"),
    )
    op.create_index(
        "ix_personaheartbeat_company_id", "personaheartbeat", ["company_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_personaheartbeat_company_id", table_name="personaheartbeat")
    op.drop_table("personaheartbeat")
