"""add_policy_config

Revision ID: c3d5f7a9e1b2
Revises: b7c1e0f4a2d9
Create Date: 2026-09-01 20:15:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c3d5f7a9e1b2"
down_revision: str | Sequence[str] | None = "b7c1e0f4a2d9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "policyconfig",
        sa.Column("id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("company_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("scope", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("scope_id", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("mode", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("default_effect", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["company.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_policyconfig_company_id", "policyconfig", ["company_id"])
    op.create_index("ix_policyconfig_scope_id", "policyconfig", ["scope_id"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_policyconfig_scope_id", table_name="policyconfig")
    op.drop_index("ix_policyconfig_company_id", table_name="policyconfig")
    op.drop_table("policyconfig")
