"""workspace manifest state (ADR-0028)

Revision ID: a9d3c5e7f128
Revises: c8f2a4d6e913
Create Date: 2026-11-01 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = "a9d3c5e7f128"
down_revision: str | Sequence[str] | None = "c8f2a4d6e913"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if "workspacemanifeststate" not in insp.get_table_names():
        op.create_table(
            "workspacemanifeststate",
            sa.Column("id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.Column("company_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.Column("person_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.Column("epoch", sa.Integer(), nullable=False),
            sa.Column("generation", sa.Integer(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["company_id"], ["company.id"]),
            sa.ForeignKeyConstraint(["person_id"], ["personnel.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("company_id", "person_id", name="uq_workspace_state"),
        )
        op.create_index(
            "ix_workspacemanifeststate_company_id",
            "workspacemanifeststate",
            ["company_id"],
        )
        op.create_index(
            "ix_workspacemanifeststate_person_id",
            "workspacemanifeststate",
            ["person_id"],
        )


def downgrade() -> None:
    op.drop_table("workspacemanifeststate")
