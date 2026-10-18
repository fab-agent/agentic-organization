"""ChangeRequest.dept_head_id references user.id (it stores the approving user)

The column was declared as a foreign key to personnel.id but has always been filled
with the approving user's id, so on PostgreSQL the first department approval would
violate the constraint. SQLite does not enforce foreign keys; nothing to do there.

Revision ID: c5e8a1d3f927
Revises: a9d2c6e4b710
Create Date: 2026-10-18 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c5e8a1d3f927"
down_revision: str | Sequence[str] | None = "a9d2c6e4b710"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NEW = "changerequest_dept_head_id_user_fkey"


def _old_fk_name() -> str | None:
    insp = sa.inspect(op.get_bind())
    for fk in insp.get_foreign_keys("changerequest"):
        if (
            fk["constrained_columns"] == ["dept_head_id"]
            and fk["referred_table"] == "personnel"
        ):
            return fk["name"]
    return None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    old = _old_fk_name()
    if old:
        op.drop_constraint(old, "changerequest", type_="foreignkey")
    insp = sa.inspect(op.get_bind())
    already = any(
        fk["constrained_columns"] == ["dept_head_id"] and fk["referred_table"] == "user"
        for fk in insp.get_foreign_keys("changerequest")
    )
    if not already:
        op.create_foreign_key(_NEW, "changerequest", "user", ["dept_head_id"], ["id"])


def downgrade() -> None:
    # The old constraint (to personnel.id) was wrong for the data stored; not restored.
    pass
