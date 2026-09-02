"""rag_into_main_db

Revision ID: e1a4c7d92f38
Revises: d9b2f4c6a8e0
Create Date: 2026-09-02 08:30:00.000000

Moves RAG storage from the separate sqlite-vec file into the main DB.
On PostgreSQL, also enables pgvector and adds a shadow vector column + HNSW index.
The old data/rag.db (if any) is simply ignored — the incremental indexer
re-populates from source records on the next run.
"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = "e1a4c7d92f38"
down_revision: str | Sequence[str] | None = "d9b2f4c6a8e0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DIM = 384


def upgrade() -> None:
    op.create_table(
        "embeddingrecord",
        sa.Column("id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("source_type", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("source_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("personnel_id", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("company_id", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("chunk_text", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("embedding", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_id"),
    )
    op.create_index(
        "ix_embeddingrecord_source_type", "embeddingrecord", ["source_type"]
    )
    op.create_index("ix_embeddingrecord_source_id", "embeddingrecord", ["source_id"])
    op.create_index(
        "ix_embeddingrecord_personnel_id", "embeddingrecord", ["personnel_id"]
    )
    op.create_index("ix_embeddingrecord_company_id", "embeddingrecord", ["company_id"])

    op.create_table(
        "ragindexstate",
        sa.Column("source_type", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column(
            "last_indexed_at", sqlmodel.sql.sqltypes.AutoString(), nullable=False
        ),
        sa.Column("total_count", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("source_type"),
    )

    if op.get_bind().dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")
        op.execute(
            f"ALTER TABLE embeddingrecord ADD COLUMN embedding_vec vector({_DIM})"
        )
        op.execute(
            "CREATE INDEX ix_embeddingrecord_vec ON embeddingrecord "
            "USING hnsw (embedding_vec vector_cosine_ops)"
        )


def downgrade() -> None:
    op.drop_table("ragindexstate")
    op.drop_index("ix_embeddingrecord_company_id", table_name="embeddingrecord")
    op.drop_index("ix_embeddingrecord_personnel_id", table_name="embeddingrecord")
    op.drop_index("ix_embeddingrecord_source_id", table_name="embeddingrecord")
    op.drop_index("ix_embeddingrecord_source_type", table_name="embeddingrecord")
    op.drop_table("embeddingrecord")
