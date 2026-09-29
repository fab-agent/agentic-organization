"""workspaces

Revision ID: b8d4f2a61c93
Revises: a7c3e5f9b214
Create Date: 2026-09-29 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = "b8d4f2a61c93"
down_revision: str | Sequence[str] | None = "a7c3e5f9b214"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workspace",
        sa.Column("id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("company_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("personnel_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("user_id", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("state", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("error", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("last_active_at", sa.DateTime(), nullable=False),
        sa.Column("suspended_at", sa.DateTime(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.Column("purge_after", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["company_id"], ["company.id"]),
        sa.ForeignKeyConstraint(["personnel_id"], ["personnel.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_workspace_company_id", "workspace", ["company_id"])
    op.create_index("ix_workspace_personnel_id", "workspace", ["personnel_id"])
    op.create_index("ix_workspace_state", "workspace", ["state"])
    op.create_index(
        "uq_workspace_active_person",
        "workspace",
        ["personnel_id"],
        unique=True,
        sqlite_where=sa.text("state != 'deleted'"),
        postgresql_where=sa.text("state != 'deleted'"),
    )


def downgrade() -> None:
    op.drop_index("uq_workspace_active_person", table_name="workspace")
    op.drop_index("ix_workspace_state", table_name="workspace")
    op.drop_index("ix_workspace_personnel_id", table_name="workspace")
    op.drop_index("ix_workspace_company_id", table_name="workspace")
    op.drop_table("workspace")
