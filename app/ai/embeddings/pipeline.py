from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from itertools import batched
from typing import Any
from uuid import UUID

from sqlalchemy import Row, and_, delete, func, or_, select, tuple_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.ai.embeddings.models import DocumentChunk, ProductEmbedding
from app.ai.embeddings.service import (
    EMBEDDING_DIMENSIONS,
    EmbeddingService,
    content_hash,
    document_text,
    product_text,
)
from app.modules.catalog.models import Brand, Category, Product, ProductDocument


@dataclass(frozen=True, slots=True)
class Chunking:
    size: int = 800
    overlap: int = 120

    def __post_init__(self) -> None:
        if not 1 <= self.size <= 4096 or not 0 <= self.overlap < self.size:
            raise ValueError(
                "Размер фрагмента должен быть от 1 до 4096, а перекрытие меньше размера."
            )

    def split(self, text: str) -> Iterator[str]:
        normalized = " ".join(text.split())
        start = 0
        while start < len(normalized):
            stop = min(start + self.size, len(normalized))
            if stop < len(normalized):
                boundary = normalized.rfind(
                    " ", start + max(self.overlap + 1, self.size // 2), stop
                )
                if boundary != -1:
                    stop = boundary
            if chunk := normalized[start:stop].strip():
                yield chunk
            if stop == len(normalized):
                break
            start = stop - self.overlap


@dataclass(slots=True)
class GenerationResult:
    products_read: int = 0
    products_written: int = 0
    documents_read: int = 0
    chunks_written: int = 0
    chunks_removed: int = 0


async def generate_embeddings(
    sessions: async_sessionmaker[AsyncSession], service: EmbeddingService, chunking: Chunking
) -> GenerationResult:
    if service.space.dimensions != EMBEDDING_DIMENSIONS:
        raise ValueError(
            f"Размерность пространства хранения должна составлять {EMBEDDING_DIMENSIONS}."
        )

    result = GenerationResult()
    await _generate_products(sessions, service, result)
    await _generate_documents(sessions, service, chunking, result)
    return result


async def _generate_products(
    sessions: async_sessionmaker[AsyncSession], service: EmbeddingService, result: GenerationResult
) -> None:
    after = None
    while True:
        async with sessions.begin() as session:
            statement = (
                select(Product, Category.name, Brand.name)
                .join(Category, Product.category_id == Category.id)
                .join(Brand, Product.brand_id == Brand.id)
                .order_by(Product.id)
                .with_for_update(read=True, of=(Product, Category, Brand))
                .limit(service.batch_size)
            )
            if after is not None:
                statement = statement.where(Product.id > after)
            rows = (await session.execute(statement)).all()
            if not rows:
                return
            result.products_read += len(rows)
            result.products_written += await _write_product_batch(session, service, rows)
            after = rows[-1][0].id


async def _write_product_batch(
    session: AsyncSession, service: EmbeddingService, rows: Sequence[Row[tuple[Product, str, str]]]
) -> int:
    space = service.space
    existing = dict(
        (
            await session.execute(
                select(ProductEmbedding.product_id, ProductEmbedding.content_hash).where(
                    ProductEmbedding.product_id.in_([product.id for product, _, _ in rows]),
                    ProductEmbedding.embedding_model == space.model,
                    ProductEmbedding.embedding_version == space.version,
                )
            )
        ).all()
    )
    changed = []
    for product, category, brand in rows:
        text = product_text(product, category, brand)
        digest = content_hash(text)
        if existing.get(product.id) != digest:
            changed.append((product.id, text, digest))
    if not changed:
        return 0

    vectors = await service.encode_batch(text for _, text, _ in changed)
    statement = insert(ProductEmbedding.__table__).values(
        [
            {
                "product_id": product_id,
                "embedding": vector,
                "embedding_model": space.model,
                "embedding_version": space.version,
                "content_hash": digest,
            }
            for (product_id, _, digest), vector in zip(changed, vectors, strict=True)
        ]
    )
    await session.execute(
        statement.on_conflict_do_update(
            constraint="uq_product_embeddings_space",
            set_={
                "embedding": statement.excluded.embedding,
                "content_hash": statement.excluded.content_hash,
                "updated_at": func.now(),
            },
        )
    )
    return len(changed)


@dataclass(frozen=True, slots=True)
class _Chunk:
    document_id: UUID
    index: int
    content: str
    text: str
    metadata: dict[str, str]


async def _generate_documents(
    sessions: async_sessionmaker[AsyncSession],
    service: EmbeddingService,
    chunking: Chunking,
    result: GenerationResult,
) -> None:
    after = None
    while True:
        async with sessions.begin() as session:
            statement = (
                select(ProductDocument)
                .order_by(ProductDocument.id)
                .with_for_update(read=True)
                .limit(service.batch_size)
            )
            if after is not None:
                statement = statement.where(ProductDocument.id > after)
            documents = (await session.scalars(statement)).all()
            if not documents:
                return

            result.documents_read += len(documents)
            counts = dict.fromkeys((document.id for document in documents), 0)
            chunks = (
                chunk for document in documents for chunk in _document_chunks(document, chunking)
            )
            for batch in batched(chunks, service.batch_size):
                for chunk in batch:
                    counts[chunk.document_id] = chunk.index + 1
                result.chunks_written += await _write_chunk_batch(session, service, batch)

            removed = await session.execute(
                delete(DocumentChunk).where(
                    DocumentChunk.embedding_model == service.space.model,
                    DocumentChunk.embedding_version == service.space.version,
                    or_(
                        *(
                            and_(
                                DocumentChunk.document_id == doc_id,
                                DocumentChunk.chunk_index >= count,
                            )
                            for doc_id, count in counts.items()
                        )
                    ),
                )
            )
            result.chunks_removed += removed.rowcount
            after = documents[-1].id


def _document_chunks(document: ProductDocument, chunking: Chunking) -> Iterator[_Chunk]:
    metadata = {
        "product_id": str(document.product_id),
        "document_type": document.document_type.value,
        "title": document.title,
        "source": document.source,
    }
    for index, chunk in enumerate(chunking.split(document.content)):
        yield _Chunk(document.id, index, chunk, document_text(document.title, chunk), metadata)


async def _write_chunk_batch(
    session: AsyncSession, service: EmbeddingService, chunks: Sequence[_Chunk]
) -> int:
    space = service.space
    rows = await session.execute(
        select(
            DocumentChunk.document_id,
            DocumentChunk.chunk_index,
            DocumentChunk.content_hash,
            DocumentChunk.chunk_metadata,
            DocumentChunk.embedding,
        ).where(
            tuple_(DocumentChunk.document_id, DocumentChunk.chunk_index).in_(
                [(chunk.document_id, chunk.index) for chunk in chunks]
            ),
            DocumentChunk.embedding_model == space.model,
            DocumentChunk.embedding_version == space.version,
        )
    )
    existing = {
        (doc_id, index): (digest, metadata, vector)
        for doc_id, index, digest, metadata, vector in rows
    }
    writes: list[dict[str, Any]] = []
    pending = []
    for chunk in chunks:
        digest = content_hash(chunk.text)
        stored = existing.get((chunk.document_id, chunk.index))
        same_text = stored is not None and stored[0] == digest
        if same_text and stored[1] == chunk.metadata:
            continue
        values = {
            "document_id": chunk.document_id,
            "chunk_index": chunk.index,
            "content": chunk.content,
            "embedding_model": space.model,
            "embedding_version": space.version,
            "content_hash": digest,
            "metadata": chunk.metadata,
        }
        if same_text:
            values["embedding"] = stored[2]
        else:
            pending.append((chunk.text, values))
        writes.append(values)

    if not writes:
        return 0
    vectors = await service.encode_batch(text for text, _ in pending)
    for (_, values), vector in zip(pending, vectors, strict=True):
        values["embedding"] = vector

    statement = insert(DocumentChunk.__table__).values(writes)
    await session.execute(
        statement.on_conflict_do_update(
            constraint="uq_document_chunks_space",
            set_={
                "content": statement.excluded.content,
                "embedding": statement.excluded.embedding,
                "content_hash": statement.excluded.content_hash,
                "metadata": statement.excluded["metadata"],
                "updated_at": func.now(),
            },
        )
    )
    return len(writes)
