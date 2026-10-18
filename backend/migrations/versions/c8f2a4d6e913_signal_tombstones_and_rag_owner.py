"""LearningSignal tombstones/revisions; EmbeddingRecord.owner_user_id (+ backfill)

Revision ID: c8f2a4d6e913
Revises: b3e6a9d1f482
Create Date: 2026-10-18 23:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = "c8f2a4d6e913"
down_revision: str | Sequence[str] | None = "b3e6a9d1f482"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _cols(table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    sig = _cols("learningsignal")
    with op.batch_alter_table("learningsignal", schema=None) as batch_op:
        if "withdrawn_at" not in sig:
            batch_op.add_column(sa.Column("withdrawn_at", sa.DateTime(), nullable=True))
        if "revisions" not in sig:
            batch_op.add_column(
                sa.Column("revisions", sa.Integer(), nullable=False, server_default="0")
            )
    if "owner_user_id" not in _cols("embeddingrecord"):
        with op.batch_alter_table("embeddingrecord", schema=None) as batch_op:
            batch_op.add_column(
                sa.Column(
                    "owner_user_id", sqlmodel.sql.sqltypes.AutoString(), nullable=True
                )
            )
            batch_op.create_index(
                "ix_embeddingrecord_owner_user_id", ["owner_user_id"], unique=False
            )
        # Owners of what is already indexed: the chat's / task's human. Records whose
        # chat has no human owner stay NULL (read only by ownerless sessions).
        op.execute(
            sa.text(
                "UPDATE embeddingrecord SET owner_user_id = ("
                "SELECT s.user_id FROM sessionmessage m JOIN agentsession s "
                "ON s.id = m.session_id WHERE m.id = embeddingrecord.source_id) "
                "WHERE source_type = 'session_message'"
            )
        )
        op.execute(
            sa.text(
                "UPDATE embeddingrecord SET owner_user_id = ("
                "SELECT t.requester_user_id FROM taskrequest t "
                "WHERE t.id = embeddingrecord.source_id) "
                "WHERE source_type = 'task_result'"
            )
        )
        op.execute(
            sa.text(
                "UPDATE embeddingrecord SET owner_user_id = ("
                "SELECT s.user_id FROM agentmemory a JOIN agentsession s "
                "ON s.id = a.session_id WHERE a.id = embeddingrecord.source_id) "
                "WHERE source_type = 'agent_memory'"
            )
        )


def downgrade() -> None:
    if "owner_user_id" in _cols("embeddingrecord"):
        with op.batch_alter_table("embeddingrecord", schema=None) as batch_op:
            batch_op.drop_column("owner_user_id")
    sig = _cols("learningsignal")
    with op.batch_alter_table("learningsignal", schema=None) as batch_op:
        for c in ("revisions", "withdrawn_at"):
            if c in sig:
                batch_op.drop_column(c)
