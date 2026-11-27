from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.tools.catalog import CatalogTools, ToolCall, ToolError
from app.modules.catalog.models import Brand, Category, Product
from app.modules.search.service import ProductSearch

pytestmark = pytest.mark.asyncio


async def test_tools_are_bounded_and_apply_filters(session: AsyncSession) -> None:
    suffix = uuid4().hex
    category = Category(name="Ноутбуки", slug=f"tools-{suffix}", description="")
    brand = Brand(name=f"Марка {suffix}", description="")
    products = [
        Product(
            category=category,
            brand=brand,
            name=f"Ноутбук {index}",
            sku=f"tools-{suffix}-{index}",
            description="Техника",
            price=Decimal(price),
            stock_quantity=1,
            specifications={"ram_gb": ram},
        )
        for index, (price, ram) in enumerate([(80_000, 32), (75_000, 32), (60_000, 8)])
    ]
    session.add_all(products)
    await session.flush()

    tools = CatalogTools(ProductSearch(None))
    args = {"product_ids": [str(products[0].id), str(products[1].id)]}
    compare = ToolCall(name="compare_products", arguments=args)
    alternative = ToolCall(
        name="find_alternatives",
        arguments={
            "product_id": str(products[0].id),
            "cheaper": True,
            "filters": {"spec": ["ram_gb:gte:32"]},
        },
    )
    comparison, alternatives = await tools.execute(session, [compare, alternative])
    assert comparison.specifications == {"ram_gb": [32, 32]}
    assert [item.id for item in alternatives.products] == [products[1].id]
    with pytest.raises(ToolError):
        await tools.execute(session, [compare] * 4)
    with pytest.raises(ValidationError):
        ToolCall(name="update_price", arguments={})
    with pytest.raises(ToolError):
        await tools.execute(session, [ToolCall(name="check_stock", arguments={"sku": "invalid"})])
