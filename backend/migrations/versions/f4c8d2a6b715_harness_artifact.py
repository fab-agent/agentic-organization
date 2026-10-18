"""harness artifacts (ADR-0022 §2) and the session pin

Revision ID: f4c8d2a6b715
Revises: e2b9c4a7d513
Create Date: 2026-10-18 19:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = "f4c8d2a6b715"
down_revision: str | Sequence[str] | None = "e2b9c4a7d513"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if "harnessartifact" not in insp.get_table_names():
        op.create_table(
            "harnessartifact",
            sa.Column("id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.Column("company_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.Column("level", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.Column("target_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.Column("kind", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.Column("key", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("base_version", sa.Integer(), nullable=False),
            sa.Column("content", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.Column(
                "content_hash", sqlmodel.sql.sqltypes.AutoString(), nullable=False
            ),
            sa.Column("status", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.Column(
                "source_cr_id", sqlmodel.sql.sqltypes.AutoString(), nullable=True
            ),
            sa.Column(
                "evidence_json", sqlmodel.sql.sqltypes.AutoString(), nullable=False
            ),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["company_id"], ["company.id"]),
            sa.ForeignKeyConstraint(["source_cr_id"], ["changerequest.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "company_id",
                "level",
                "target_id",
                "kind",
                "key",
                "version",
                name="uq_harness_version",
            ),
        )
        op.create_index(
            "ix_harnessartifact_company_id", "harnessartifact", ["company_id"]
        )
    cols = {c["name"] for c in insp.get_columns("agentsession")}
    if "harness_json" not in cols:
        with op.batch_alter_table("agentsession", schema=None) as batch_op:
            batch_op.add_column(
                sa.Column(
                    "harness_json", sqlmodel.sql.sqltypes.AutoString(), nullable=True
                )
            )


def downgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if "harness_json" in {c["name"] for c in insp.get_columns("agentsession")}:
        with op.batch_alter_table("agentsession", schema=None) as batch_op:
            batch_op.drop_column("harness_json")
    if "harnessartifact" in insp.get_table_names():
        op.drop_table("harnessartifact")
