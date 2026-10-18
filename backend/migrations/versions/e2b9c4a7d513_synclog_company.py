"""SyncLog.company_id — scope git sync logs to their company

Revision ID: e2b9c4a7d513
Revises: d7a3f1b8e426
Create Date: 2026-10-18 17:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = "e2b9c4a7d513"
down_revision: str | Sequence[str] | None = "d7a3f1b8e426"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    cols = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("synclog")}
    if "company_id" in cols:  # fresh create_all databases already have it
        return
    with op.batch_alter_table("synclog", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("company_id", sqlmodel.sql.sqltypes.AutoString(), nullable=True)
        )
        batch_op.create_index("ix_synclog_company_id", ["company_id"], unique=False)
        batch_op.create_foreign_key(
            "fk_synclog_company_id", "company", ["company_id"], ["id"]
        )


def downgrade() -> None:
    cols = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("synclog")}
    if "company_id" not in cols:
        return
    with op.batch_alter_table("synclog", schema=None) as batch_op:
        batch_op.drop_column("company_id")
