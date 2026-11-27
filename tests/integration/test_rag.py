import json
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.intent import Intent, IntentQuery
from app.ai.rag.retrieval import RagRetriever
from app.ai.rag.service import RagService
from app.modules.catalog.models import Brand, Category, DocumentType, Product, ProductDocument
from app.modules.catalog.schemas import ProductFilters
from app.modules.search.service import ProductSearch

pytestmark = pytest.mark.asyncio


class FakeLLM:
    model = "test"

    def __init__(self):
        self.invalid = True

    async def generate(self, messages, *, schema=None):
        data = json.loads(messages[1].content)
        assert len(messages[1].content) <= 8_000
        assert len(data["products"]) == 1
        assert len(data["evidence"]) == 1
        return json.dumps(
            {
                "product_ids": [str(uuid4()) if self.invalid else data["products"][0]["id"]],
                "document_ids": [data["evidence"][0]["reference"]["document_id"]],
                "emphasis": "price",
            }
        )


async def test_rag_builds_bounded_context_and_validates_model_facts(session: AsyncSession) -> None:
    suffix = uuid4().hex
    category = Category(slug=f"rag-{suffix}", name="Ноутбуки", description="")
    brand = Brand(name=f"Альта {suffix}", description="")
    eligible = None
    for index, price in enumerate((70_000, 95_000)):
        product = Product(
            name=f"Ноутбук {index}",
            sku=f"{suffix}-{index}",
            category=category,
            brand=brand,
            description="Для программирования",
            price=Decimal(price),
            specifications={"ram_gb": 32},
            stock_quantity=2,
        )
        session.add(product)
        if index == 0:
            eligible = product
            session.add(
                ProductDocument(
                    product=product,
                    document_type=DocumentType.PRODUCT_MANUAL,
                    title="Установка",
                    content="Подключите адаптер. " * 300,
                    source="catalog/setup",
                )
            )
    await session.flush()
    request = IntentQuery(
        intent=Intent.RECOMMENDATION,
        query="программирование",
        filters=ProductFilters(category_slug=category.slug, max_price=80_000),
    )
    llm = FakeLLM()
    service = RagService(RagRetriever(ProductSearch(None)), llm)
    fallback = await service.answer(session, request)
    assert fallback.metadata.mode == "catalog"
    assert [item.id for item in fallback.recommended_products] == [eligible.id]
    assert "70000.00" in fallback.answer
    assert "95000.00" not in fallback.answer

    llm.invalid = False
    grounded = await service.answer(session, request)
    assert grounded.metadata.mode == "model"
    assert grounded.sources[0].source == "catalog/setup"
    assert grounded.recommended_products[0].id == eligible.id
