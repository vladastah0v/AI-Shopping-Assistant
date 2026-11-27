import asyncio
import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.embeddings.service import EmbeddingService, Vector
from app.ai.retrieval.fusion import reciprocal_rank_fusion
from app.ai.retrieval.keyword import search_products_by_keywords
from app.ai.retrieval.vector import VectorSearchOptions, search_product_vectors
from app.modules.catalog.repository import get_products_by_id
from app.modules.catalog.schemas import ProductRead
from app.modules.search.schemas import RankedProduct, SearchRequest, SearchResponse, SearchStrategy

logger = logging.getLogger(__name__)


class EmbeddingsUnavailable(Exception):
    pass


class ProductSearch:
    def __init__(self, embeddings: EmbeddingService | None, *, embedding_timeout: float = 8):
        self.embeddings = embeddings
        self.embedding_timeout = embedding_timeout
        self._embedding_slot = asyncio.Semaphore(1)
        self._embedding_task: asyncio.Task[Vector] | None = None

    async def search(
        self, session: AsyncSession, request: SearchRequest, strategy: SearchStrategy
    ) -> SearchResponse:
        applied = strategy
        depth = min(100, request.top_k * 4) if strategy == "hybrid" else request.top_k
        semantic: list[tuple[UUID, float]] = []
        if strategy != "keyword":
            try:
                semantic = await self._semantic(session, request, depth)
            except EmbeddingsUnavailable:
                if strategy == "semantic":
                    raise
                applied = "keyword"
        keyword = []
        if strategy != "semantic":
            keyword = [
                (match.product_id, match.score)
                for match in await search_products_by_keywords(
                    session, request.query, filters=request.filters, top_k=depth
                )
            ]
        if applied == "hybrid":
            ranking = reciprocal_rank_fusion(
                (item for item, _ in keyword), (item for item, _ in semantic)
            )
        else:
            ranking = keyword if applied == "keyword" else semantic

        products = await get_products_by_id(
            session, [item for item, _ in ranking], filters=request.filters
        )
        return SearchResponse(
            strategy=strategy,
            applied_strategy=applied,
            items=[
                RankedProduct(product=ProductRead.model_validate(products[item]), score=score)
                for item, score in ranking
                if item in products
            ][: request.top_k],
        )

    async def _semantic(
        self, session: AsyncSession, request: SearchRequest, depth: int
    ) -> list[tuple[UUID, float]]:
        vector = await self.query_vector(request.query)
        assert self.embeddings is not None
        rows = await search_product_vectors(
            session,
            vector,
            self.embeddings.space,
            filters=request.filters,
            options=VectorSearchOptions(top_k=depth),
        )
        return [(row.product_id, 1 - row.distance) for row in rows]

    async def query_vector(self, query: str) -> Vector:
        if self.embeddings is None:
            raise EmbeddingsUnavailable("Семантический поиск недоступен.")
        try:
            async with asyncio.timeout(self.embedding_timeout):
                await self._embedding_slot.acquire()
                self._embedding_task = asyncio.create_task(self.embeddings.encode_query(query))
                self._embedding_task.add_done_callback(self._release_embedding_slot)
                return await asyncio.shield(self._embedding_task)
        except (RuntimeError, ValueError, TimeoutError) as error:
            raise EmbeddingsUnavailable("Семантический поиск недоступен.") from error

    def _release_embedding_slot(self, task: asyncio.Task[Vector]) -> None:
        self._embedding_slot.release()
        self._embedding_task = None
        if not task.cancelled() and task.exception() is not None:
            logger.warning(
                "Query embedding failed", extra={"error_type": type(task.exception()).__name__}
            )
