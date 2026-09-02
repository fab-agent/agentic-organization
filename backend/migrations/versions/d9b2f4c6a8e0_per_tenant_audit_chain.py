"""per_tenant_audit_chain

Revision ID: d9b2f4c6a8e0
Revises: c3d5f7a9e1b2
Create Date: 2026-09-01 21:00:00.000000

Rebuilds `auditevent` with a per-tenant chain: composite PK (chain_key, seq).
The table was introduced one migration ago (b7c1e0f4a2d9) and holds no
production data, so this drops and recreates it rather than doing an in-place
PK change.
"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = "d9b2f4c6a8e0"
down_revision: str | Sequence[str] | None = "c3d5f7a9e1b2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _create() -> None:
    op.create_table(
        "auditevent",
        sa.Column("chain_key", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("prev_hash", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("hash", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("actor_type", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("actor_id", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("company_id", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("action", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("target", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("reason", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("payload_json", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("chain_key", "seq"),
    )
    op.create_index("ix_auditevent_hash", "auditevent", ["hash"])
    op.create_index("ix_auditevent_actor_id", "auditevent", ["actor_id"])
    op.create_index("ix_auditevent_company_id", "auditevent", ["company_id"])


def _drop() -> None:
    op.drop_index("ix_auditevent_company_id", table_name="auditevent")
    op.drop_index("ix_auditevent_actor_id", table_name="auditevent")
    op.drop_index("ix_auditevent_hash", table_name="auditevent")
    op.drop_table("auditevent")


def upgrade() -> None:
    """Upgrade schema."""
    _drop()
    _create()


def downgrade() -> None:
    """Downgrade schema."""
    _drop()
    op.create_table(
        "auditevent",
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("prev_hash", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("hash", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("actor_type", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("actor_id", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("company_id", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("action", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("target", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("reason", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("payload_json", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("seq"),
    )
    op.create_index("ix_auditevent_hash", "auditevent", ["hash"])
    op.create_index("ix_auditevent_actor_id", "auditevent", ["actor_id"])
    op.create_index("ix_auditevent_company_id", "auditevent", ["company_id"])
