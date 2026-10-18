"""AgentSession.user_id — who started the chat

Revision ID: d7a3f1b8e426
Revises: c5e8a1d3f927
Create Date: 2026-10-18 15:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = "d7a3f1b8e426"
down_revision: str | Sequence[str] | None = "c5e8a1d3f927"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    cols = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("agentsession")}
    if "user_id" in cols:  # fresh create_all databases already have it
        return
    with op.batch_alter_table("agentsession", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("user_id", sqlmodel.sql.sqltypes.AutoString(), nullable=True)
        )
        batch_op.create_index("ix_agentsession_user_id", ["user_id"], unique=False)
        batch_op.create_foreign_key(
            "fk_agentsession_user_id", "user", ["user_id"], ["id"]
        )


def downgrade() -> None:
    with op.batch_alter_table("agentsession", schema=None) as batch_op:
        batch_op.drop_constraint("fk_agentsession_user_id", type_="foreignkey")
        batch_op.drop_index("ix_agentsession_user_id")
        batch_op.drop_column("user_id")
