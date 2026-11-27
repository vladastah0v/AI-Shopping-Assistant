from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.intent import IntentQuery
from app.ai.rag.schemas import Evidence, SourceReference
from app.ai.retrieval.fusion import reciprocal_rank_fusion
from app.ai.retrieval.keyword import search_documents_by_keywords
from app.ai.retrieval.vector import VectorSearchOptions, search_document_vectors
from app.modules.catalog.models import ProductDocument
from app.modules.catalog.repository import list_products
from app.modules.catalog.schemas import ProductQuery, ProductRead
from app.modules.search.schemas import SearchRequest
from app.modules.search.service import EmbeddingsUnavailable, ProductSearch


@dataclass(slots=True)
class RagContext:
    products: list[ProductRead] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)


class RagRetriever:
    def __init__(self, search: ProductSearch, *, top_k: int = 6) -> None:
        if not 1 <= top_k <= 20:
            raise ValueError("Количество кандидатов должно быть от 1 до 20.")
        self.search = search
        self.top_k = top_k

    async def retrieve(self, session: AsyncSession, request: IntentQuery) -> RagContext:
        use_semantic = False
        filters = request.filters.model_dump(exclude_none=True, exclude_defaults=True)
        if request.query:
            result = await self.search.search(
                session,
                SearchRequest(query=request.query, filters=request.filters, top_k=self.top_k),
                "hybrid",
            )
            products = [row.product for row in result.items]
            use_semantic = result.applied_strategy == "hybrid"
        elif filters:
            products = [
                ProductRead.model_validate(row)
                for row in (
                    await list_products(
                        session, ProductQuery(limit=self.top_k, sort="rating_desc", **filters)
                    )
                )[: self.top_k]
            ]
        else:
            return RagContext()
        return RagContext(
            products,
            await self.retrieve_evidence(session, request, products, use_semantic=use_semantic),
        )

    async def retrieve_evidence(
        self,
        session: AsyncSession,
        request: IntentQuery,
        products: list[ProductRead],
        *,
        use_semantic: bool = False,
    ) -> list[Evidence]:
        if not products:
            return []
        product_ids = {product.id for product in products}
        keywords = []
        if request.query:
            keywords = [
                item.document_id
                for item in await search_documents_by_keywords(
                    session, request.query, filters=request.filters, top_k=40
                )
                if item.product_id in product_ids
            ]
        chunks = {}
        if use_semantic and self.search.embeddings is not None:
            try:
                vector = await self.search.query_vector(request.query)
            except EmbeddingsUnavailable:
                pass
            else:
                matches = await search_document_vectors(
                    session,
                    vector,
                    self.search.embeddings.space,
                    filters=request.filters,
                    options=VectorSearchOptions(top_k=40),
                )
                for match in matches:
                    if match.product_id in product_ids:
                        chunks.setdefault(match.document_id, match)

        priority = {
            key: rank for rank, (key, _) in enumerate(reciprocal_rank_fusion(keywords, chunks))
        }
        excerpt = func.left(ProductDocument.content, 600)
        # Read a bounded number of fallback documents per product.
        selected = (
            select(
                ProductDocument.id.label("document_id"),
                ProductDocument.product_id,
                ProductDocument.document_type,
                ProductDocument.title,
                ProductDocument.source,
                excerpt.label("excerpt"),
                func.row_number()
                .over(
                    partition_by=ProductDocument.product_id,
                    order_by=(ProductDocument.document_type, ProductDocument.id),
                )
                .label("position"),
            )
            .where(ProductDocument.product_id.in_(product_ids))
            .subquery()
        )
        statement = (
            select(selected)
            .where((selected.c.position <= 2) | selected.c.document_id.in_(priority))
            .order_by(selected.c.position, selected.c.document_id)
        )
        rows = (await session.execute(statement)).mappings().all()
        evidence: list[Evidence] = []
        seen: set[tuple[object, str]] = set()
        for row in sorted(rows, key=lambda item: priority.get(item["document_id"], len(priority))):
            chunk = chunks.get(row["document_id"])
            text = " ".join((chunk.content if chunk else row["excerpt"]).split())[:600]
            key = (row["product_id"], text)
            if key in seen:
                continue
            seen.add(key)
            reference = SourceReference.model_validate(
                {**row, "chunk_id": chunk.chunk_id if chunk else None}
            )
            evidence.append(Evidence(reference=reference, excerpt=text))
            if len(evidence) == 12:
                break
        return evidence
