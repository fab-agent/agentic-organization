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


def _columns(table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    # Idempotent: a schema built with create_all from current models (fresh
    # installs, the Postgres smoke test) already has these columns.
    agent_cols = _columns("agentconfig")
    if "provider" not in agent_cols:
        with op.batch_alter_table("agentconfig") as batch_op:
            batch_op.add_column(
                sa.Column("provider", sqlmodel.sql.sqltypes.AutoString(), nullable=True)
            )
    key_cols = _columns("providerkey")
    new_key_cols = [c for c in ("display_name", "models_json") if c not in key_cols]
    if new_key_cols:
        with op.batch_alter_table("providerkey") as batch_op:
            for name in new_key_cols:
                batch_op.add_column(
                    sa.Column(name, sqlmodel.sql.sqltypes.AutoString(), nullable=True)
                )


def downgrade() -> None:
    with op.batch_alter_table("providerkey") as batch_op:
        batch_op.drop_column("models_json")
        batch_op.drop_column("display_name")
    with op.batch_alter_table("agentconfig") as batch_op:
        batch_op.drop_column("provider")
