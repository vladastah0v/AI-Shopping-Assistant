"""Create partial cosine HNSW indexes for the initial embedding space."""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

_MODEL = "intfloat/multilingual-e5-small"
_VERSION = "614241f622f53c4eeff9890bdc4f31cfecc418b3:fp32-l2-512-v1"
_INDEXES = (
    ("product_embeddings", "ix_product_embeddings_hnsw_cosine"),
    ("document_chunks", "ix_document_chunks_hnsw_cosine"),
)


def upgrade() -> None:
    for table, index in _INDEXES:
        op.create_index(
            index,
            table,
            ["embedding"],
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_where=sa.and_(
                sa.column("embedding_model", sa.String()) == _MODEL,
                sa.column("embedding_version", sa.String()) == _VERSION,
            ),
        )


def downgrade() -> None:
    for table, index in reversed(_INDEXES):
        op.drop_index(index, table_name=table)
