"""persona token revocation (ADR-0007)

Revision ID: b7d1e93a4c25
Revises: a4e6c8b02d17
Create Date: 2026-09-02 14:05:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = "b7d1e93a4c25"
down_revision: str | Sequence[str] | None = "a4e6c8b02d17"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "revokedtoken",
        sa.Column("jti", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("persona_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("company_id", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("reason", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("jti"),
    )
    op.create_index("ix_revokedtoken_persona_id", "revokedtoken", ["persona_id"])
    op.create_index("ix_revokedtoken_company_id", "revokedtoken", ["company_id"])

    op.create_table(
        "personatokenstate",
        sa.Column("persona_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("company_id", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("not_before", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("persona_id"),
    )
    op.create_index(
        "ix_personatokenstate_company_id", "personatokenstate", ["company_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_personatokenstate_company_id", table_name="personatokenstate")
    op.drop_table("personatokenstate")
    op.drop_index("ix_revokedtoken_company_id", table_name="revokedtoken")
    op.drop_index("ix_revokedtoken_persona_id", table_name="revokedtoken")
    op.drop_table("revokedtoken")
