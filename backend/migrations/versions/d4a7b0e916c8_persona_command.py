"""persona command channel (ADR-0010 layer 5)

Revision ID: d4a7b0e916c8
Revises: c8e2f04b1d37
Create Date: 2026-09-03 08:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = "d4a7b0e916c8"
down_revision: str | Sequence[str] | None = "c8e2f04b1d37"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "personacommand",
        sa.Column("id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("persona_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("company_id", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("kind", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("payload_json", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("issued_by", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("delivered_at", sa.DateTime(), nullable=True),
        sa.Column("acked_at", sa.DateTime(), nullable=True),
        sa.Column("result", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_personacommand_persona_id", "personacommand", ["persona_id"])
    op.create_index("ix_personacommand_company_id", "personacommand", ["company_id"])


def downgrade() -> None:
    op.drop_index("ix_personacommand_company_id", table_name="personacommand")
    op.drop_index("ix_personacommand_persona_id", table_name="personacommand")
    op.drop_table("personacommand")
