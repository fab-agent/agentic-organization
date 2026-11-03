"""heartbeat records whether the policy was ready (ADR-0038)

Revision ID: d5a1b7c3f024
Revises: c4f8a2d6e913
Create Date: 2026-11-03 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d5a1b7c3f024"
down_revision: str | Sequence[str] | None = "c4f8a2d6e913"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COLS = (
    ("policy_ready", sa.Boolean()),
    ("policy_reason", sa.String()),
    ("policy_mode", sa.String()),
)


def upgrade() -> None:
    have = {
        c["name"] for c in sa.inspect(op.get_bind()).get_columns("personaheartbeat")
    }
    for name, typ in _COLS:
        if name not in have:
            op.add_column("personaheartbeat", sa.Column(name, typ, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("personaheartbeat") as b:
        for name, _ in reversed(_COLS):
            b.drop_column(name)
