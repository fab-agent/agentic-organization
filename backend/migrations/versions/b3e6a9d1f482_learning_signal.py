"""learning signals (ADR-0022 §3)

Revision ID: b3e6a9d1f482
Revises: a1d5e7c3b926
Create Date: 2026-10-18 22:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = "b3e6a9d1f482"
down_revision: str | Sequence[str] | None = "a1d5e7c3b926"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if "learningsignal" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "learningsignal",
        sa.Column("id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("company_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("personnel_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("persona_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("user_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("session_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("message_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("kind", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("note", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["company.id"]),
        sa.ForeignKeyConstraint(["personnel_id"], ["personnel.id"]),
        sa.ForeignKeyConstraint(["persona_id"], ["personnel.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
        sa.ForeignKeyConstraint(["session_id"], ["agentsession.id"]),
        sa.ForeignKeyConstraint(["message_id"], ["sessionmessage.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "message_id", "kind", name="uq_learning_signal"),
    )
    for col in ("company_id", "personnel_id", "persona_id"):
        op.create_index(f"ix_learningsignal_{col}", "learningsignal", [col])


def downgrade() -> None:
    if "learningsignal" in sa.inspect(op.get_bind()).get_table_names():
        op.drop_table("learningsignal")
