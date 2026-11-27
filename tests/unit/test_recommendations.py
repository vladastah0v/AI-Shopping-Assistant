from decimal import Decimal
from uuid import UUID

from app.ai.intent import Intent, IntentQuery, infer_intent
from app.ai.rag.recommendations import recommend
from app.modules.catalog.schemas import BrandSummary, CategorySummary, ProductRead


def product(index: int, price: int, ram: int) -> ProductRead:
    return ProductRead(
        id=UUID(int=index),
        sku=f"SKU-{index}",
        name=f"Ноутбук {index}",
        category=CategorySummary(id=UUID(int=10), slug="laptops", name="Ноутбуки"),
        brand=BrandSummary(id=UUID(int=11), name="Зенит"),
        price=Decimal(price),
        currency="RUB",
        stock_quantity=1,
        rating=None,
        description="Ноутбук",
        specifications={"ram_gb": ram},
    )


def test_explains_distinct_recommendations() -> None:
    rows = [product(1, 70_000, 16), product(2, 60_000, 8), product(3, 80_000, 32)]
    request = IntentQuery(intent=Intent.RECOMMENDATION)
    output = recommend(request, rows)
    assert [item.kind for item in output] == ["optimal", "budget", "specifications"]
    assert [item.product_id for item in output] == [row.id for row in rows]

    alternative = infer_intent("Есть подешевле?")
    assert [item.kind for item in recommend(alternative, rows)] == ["alternative"] * 3
