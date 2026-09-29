"""workspace agent flag and personnel job_description (ADR-0019)

Revision ID: c9e5a3b72d14
Revises: b8d4f2a61c93
Create Date: 2026-09-29 15:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c9e5a3b72d14"
down_revision: str | Sequence[str] | None = "b8d4f2a61c93"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("personnel") as batch_op:
        batch_op.add_column(sa.Column("job_description", sa.String(), nullable=True))
    with op.batch_alter_table("agentconfig") as batch_op:
        batch_op.add_column(
            sa.Column(
                "is_workspace_agent",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
    op.create_index(
        "uq_agentconfig_workspace_agent",
        "agentconfig",
        ["responsible_id"],
        unique=True,
        sqlite_where=sa.text("is_workspace_agent = 1"),
        postgresql_where=sa.text("is_workspace_agent"),
    )


def downgrade() -> None:
    op.drop_index("uq_agentconfig_workspace_agent", table_name="agentconfig")
    with op.batch_alter_table("agentconfig") as batch_op:
        batch_op.drop_column("is_workspace_agent")
    with op.batch_alter_table("personnel") as batch_op:
        batch_op.drop_column("job_description")
