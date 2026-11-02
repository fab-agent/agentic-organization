"""workspace client drift report (ADR-0035)

Revision ID: b7e3a9c1d452
Revises: a9d3c5e7f128
Create Date: 2026-11-02 21:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = "b7e3a9c1d452"
down_revision: str | Sequence[str] | None = "a9d3c5e7f128"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if "workspaceclientreport" not in insp.get_table_names():
        op.create_table(
            "workspaceclientreport",
            sa.Column("id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.Column("company_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.Column("person_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.Column(
                "client_version", sqlmodel.sql.sqltypes.AutoString(), nullable=False
            ),
            sa.Column("epoch", sa.BigInteger(), nullable=False),
            sa.Column("generation", sa.BigInteger(), nullable=False),
            sa.Column("missing", sa.Integer(), nullable=False),
            sa.Column("modified", sa.Integer(), nullable=False),
            sa.Column("extra", sa.Integer(), nullable=False),
            sa.Column("unmanaged", sa.Integer(), nullable=False),
            sa.Column("interrupted", sa.Boolean(), nullable=False),
            sa.Column("received_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["company_id"], ["company.id"]),
            sa.ForeignKeyConstraint(["person_id"], ["personnel.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "company_id", "person_id", name="uq_workspace_client_report"
            ),
        )
        op.create_index(
            "ix_workspaceclientreport_company_id",
            "workspaceclientreport",
            ["company_id"],
        )
        op.create_index(
            "ix_workspaceclientreport_person_id",
            "workspaceclientreport",
            ["person_id"],
        )


def downgrade() -> None:
    op.drop_table("workspaceclientreport")
