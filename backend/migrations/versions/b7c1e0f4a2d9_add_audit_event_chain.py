"""add_audit_event_chain

Revision ID: b7c1e0f4a2d9
Revises: 7ed610efc189
Create Date: 2026-09-01 19:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b7c1e0f4a2d9"
down_revision: str | Sequence[str] | None = "7ed610efc189"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
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


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_auditevent_company_id", table_name="auditevent")
    op.drop_index("ix_auditevent_actor_id", table_name="auditevent")
    op.drop_index("ix_auditevent_hash", table_name="auditevent")
    op.drop_table("auditevent")
