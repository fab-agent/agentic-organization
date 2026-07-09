"""add_telegramconfig

Revision ID: a3f9c12e8b45
Revises: 48b730a4a8bb
Create Date: 2026-07-09 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


revision: str = 'a3f9c12e8b45'
down_revision: Union[str, Sequence[str], None] = '48b730a4a8bb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'telegramconfig',
        sa.Column('id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('company_id', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('encrypted_token', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('admin_chat_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['company_id'], ['company.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_telegramconfig_company_id', 'telegramconfig', ['company_id'])


def downgrade() -> None:
    op.drop_index('ix_telegramconfig_company_id', 'telegramconfig')
    op.drop_table('telegramconfig')
