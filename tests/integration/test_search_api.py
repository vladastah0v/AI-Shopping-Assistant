from decimal import Decimal
from uuid import uuid4

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.embeddings.huggingface import E5_SMALL
from app.ai.embeddings.models import ProductEmbedding
from app.ai.embeddings.service import EmbeddingService
from app.main import create_app
from app.modules.catalog.models import Brand, Category, Product
from app.modules.search.router import search_session
from app.modules.search.service import ProductSearch

pytestmark = pytest.mark.asyncio


class TestVectors:
    __test__ = False
    space = E5_SMALL

    async def encode_batch(self, texts):
        return [[1, *([0] * 383)] for _ in texts]


async def test_search_strategies_and_fallback(session: AsyncSession) -> None:
    suffix = uuid4().hex
    category = Category(name="Ноутбуки", slug=f"search-{suffix}", description="")
    brand = Brand(name=f"Бренд {suffix}", description="")
    for index, (name, price, ram) in enumerate(
        [("Ноутбук", 70_000, 32), ("Ноутбук", 100_000, 32), ("Ноутбук", 60_000, 8)]
    ):
        product = Product(
            name=name,
            sku=f"{suffix}-{index}",
            category=category,
            brand=brand,
            description="Для разработки",
            price=Decimal(price),
            stock_quantity=1,
            specifications={"ram_gb": ram},
        )
        session.add(product)
        await session.flush()
        session.add(
            ProductEmbedding(
                product_id=product.id,
                embedding_model=E5_SMALL.model,
                embedding_version=E5_SMALL.version,
                embedding=[1, *([0] * 383)],
                content_hash="f" * 64,
            )
        )
    await session.flush()

    app = create_app()
    app.dependency_overrides[search_session] = lambda: session
    app.state.product_search = ProductSearch(EmbeddingService(TestVectors()))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test/api/v1/search/"
    ) as client:
        body = {
            "query": "ноутбуком",
            "filters": {
                "category_slug": category.slug,
                "max_price": 80_000,
                "spec": ["ram_gb:gte:16"],
                "in_stock": True,
            },
        }
        for strategy in ("keyword", "semantic", "hybrid"):
            response = await client.post(strategy, json=body)
            assert response.status_code == 200
            result = response.json()
            assert result["applied_strategy"] == strategy
            assert [row["product"]["sku"] for row in result["items"]] == [f"{suffix}-0"]
        assert (await client.post("keyword", json={"query": " "})).status_code == 422
        app.state.product_search = ProductSearch(None)
        assert (await client.post("semantic", json=body)).status_code == 503
        assert (await client.post("hybrid", json=body)).json()["applied_strategy"] == "keyword"
