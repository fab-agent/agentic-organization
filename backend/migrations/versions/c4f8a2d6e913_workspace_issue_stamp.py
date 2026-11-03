"""workspace manifest issuance spacing (ADR-0037)

Revision ID: c4f8a2d6e913
Revises: b7e3a9c1d452
Create Date: 2026-11-03 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = "c4f8a2d6e913"
down_revision: str | Sequence[str] | None = "b7e3a9c1d452"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if "workspaceissuestamp" not in insp.get_table_names():
        op.create_table(
            "workspaceissuestamp",
            sa.Column("id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.Column("company_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.Column("person_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.Column("issued_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["company_id"], ["company.id"]),
            sa.ForeignKeyConstraint(["person_id"], ["personnel.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "company_id", "person_id", name="uq_workspace_issue_stamp"
            ),
        )
        op.create_index(
            "ix_workspaceissuestamp_company_id", "workspaceissuestamp", ["company_id"]
        )
        op.create_index(
            "ix_workspaceissuestamp_person_id", "workspaceissuestamp", ["person_id"]
        )


def downgrade() -> None:
    op.drop_table("workspaceissuestamp")
