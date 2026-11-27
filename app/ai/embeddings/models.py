from datetime import datetime
from typing import Any
from uuid import UUID

from pgvector.sqlalchemy import VECTOR
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Table,
    Text,
    UniqueConstraint,
    and_,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.ai.embeddings.huggingface import E5_SMALL
from app.ai.embeddings.service import EMBEDDING_DIMENSIONS
from app.core.database import Base

EMBEDDINGS_LOCK_KEY = "shopping_assistant.embeddings"


class ProductEmbedding(Base):
    __tablename__ = "product_embeddings"
    __table_args__ = (
        UniqueConstraint(
            "product_id", "embedding_model", "embedding_version", name="uq_product_embeddings_space"
        ),
        CheckConstraint("content_hash ~ '^[0-9a-f]{64}$'", name="content_hash_format"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, server_default=func.gen_random_uuid())
    product_id: Mapped[UUID] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"))
    embedding: Mapped[Any] = mapped_column(VECTOR(EMBEDDING_DIMENSIONS), nullable=False)
    embedding_model: Mapped[str] = mapped_column(String(160))
    embedding_version: Mapped[str] = mapped_column(String(160))
    content_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DocumentChunk(Base):
    __tablename__ = "document_chunks"
    __table_args__ = (
        UniqueConstraint(
            "document_id",
            "chunk_index",
            "embedding_model",
            "embedding_version",
            name="uq_document_chunks_space",
        ),
        CheckConstraint("chunk_index >= 0", name="chunk_index_non_negative"),
        CheckConstraint("btrim(content) <> ''", name="content_not_blank"),
        CheckConstraint("content_hash ~ '^[0-9a-f]{64}$'", name="content_hash_format"),
        CheckConstraint("jsonb_typeof(metadata) = 'object'", name="metadata_object"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, server_default=func.gen_random_uuid())
    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("product_documents.id", ondelete="CASCADE")
    )
    chunk_index: Mapped[int]
    content: Mapped[str] = mapped_column(Text)
    embedding: Mapped[Any] = mapped_column(VECTOR(EMBEDDING_DIMENSIONS), nullable=False)
    embedding_model: Mapped[str] = mapped_column(String(160))
    embedding_version: Mapped[str] = mapped_column(String(160))
    content_hash: Mapped[str] = mapped_column(String(64))
    chunk_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


HNSW_INDEXES = (
    (ProductEmbedding.__table__, "ix_product_embeddings_hnsw_cosine"),
    (DocumentChunk.__table__, "ix_document_chunks_hnsw_cosine"),
)


def hnsw_index(table: Table, name: str, model: str, version: str) -> Index:
    return Index(
        name,
        table.c.embedding,
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
        postgresql_with={"m": 16, "ef_construction": 64},
        postgresql_where=and_(
            table.c.embedding_model == model, table.c.embedding_version == version
        ),
    )


for _table, _name in HNSW_INDEXES:
    hnsw_index(_table, _name, E5_SMALL.model, E5_SMALL.version)
