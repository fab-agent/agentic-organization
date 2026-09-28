"""openai-compatible endpoints: explicit agent provider, custom endpoint metadata

Revision ID: a7c3e5f9b214
Revises: d4a7b0e916c8
Create Date: 2026-09-28 19:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = "a7c3e5f9b214"
down_revision: str | Sequence[str] | None = "d4a7b0e916c8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("agentconfig") as batch_op:
        batch_op.add_column(
            sa.Column("provider", sqlmodel.sql.sqltypes.AutoString(), nullable=True)
        )
    with op.batch_alter_table("providerkey") as batch_op:
        batch_op.add_column(
            sa.Column("display_name", sqlmodel.sql.sqltypes.AutoString(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("models_json", sqlmodel.sql.sqltypes.AutoString(), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("providerkey") as batch_op:
        batch_op.drop_column("models_json")
        batch_op.drop_column("display_name")
    with op.batch_alter_table("agentconfig") as batch_op:
        batch_op.drop_column("provider")
