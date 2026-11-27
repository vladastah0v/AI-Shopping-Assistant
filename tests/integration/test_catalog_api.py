from collections.abc import AsyncIterator
from dataclasses import dataclass
from decimal import Decimal
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import create_app
from app.modules.catalog.models import Brand, Category, Product
from app.modules.catalog.router import _catalog_session

pytestmark = pytest.mark.asyncio


@dataclass
class Catalog:
    root: Category
    leaf: Category
    brand: Brand
    products: dict[str, Product]


@pytest_asyncio.fixture
async def client(session: AsyncSession) -> AsyncIterator[httpx.AsyncClient]:
    application = create_app()

    async def test_session() -> AsyncSession:
        return session

    application.dependency_overrides[_catalog_session] = test_session
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=application), base_url="http://test/api/v1/"
    ) as client:
        yield client


@pytest_asyncio.fixture
async def catalog(session: AsyncSession) -> Catalog:
    suffix = uuid4().hex
    root = Category(name="Техника", slug=f"tech-{suffix}", description="Электроника")
    middle = Category(name="Компьютеры", slug=f"computers-{suffix}", description="", parent=root)
    leaf = Category(name="Ноутбуки", slug=f"laptops-{suffix}", description="", parent=middle)
    brand = Brand(name=f"Астролив {suffix}", description="Компьютерная техника")
    other_brand = Brand(name=f"Кельмавир {suffix}", description="")
    products = {}
    variants = {
        "alpha": (
            brand,
            "79999.90",
            "RUB",
            4,
            True,
            {"ram_gb": 32, "os": "Linux", "depth_mm": 200},
        ),
        "beta": (brand, "75000.00", "RUB", 0, True, {"ram_gb": 16, "ssd_gb": 512}),
        "gamma": (
            other_brand,
            "79999.90",
            "RUB",
            2,
            True,
            {"ram_gb": 32, "depth_mm": "нет данных"},
        ),
        "import": (brand, "950.00", "USD", 1, True, {"ram_gb": 8}),
        "hidden": (brand, "15000.00", "RUB", 55, False, {"ram_gb": 64}),
    }
    for name, (item_brand, price, currency, stock, active, specifications) in variants.items():
        products[name] = Product(
            category=leaf,
            brand=item_brand,
            name=f"Модель {name}",
            sku=f"TEST-{suffix}-{name}",
            description="Техническое описание модели.",
            price=Decimal(price),
            currency=currency,
            stock_quantity=stock,
            is_active=active,
            specifications=specifications,
        )
    session.add_all(products.values())
    await session.flush()
    return Catalog(root, leaf, brand, products)


async def test_category_and_brand_endpoints(client: httpx.AsyncClient, catalog: Catalog) -> None:
    categories = await client.get("categories?limit=100")
    brands_page = await client.get("brands?limit=1")
    brands = await client.get("brands?limit=100")

    assert categories.status_code == brands_page.status_code == brands.status_code == 200
    entries = {row["id"]: row for row in categories.json()["items"]}
    assert entries[str(catalog.root.id)]["parent_id"] is None
    assert entries[str(catalog.leaf.id)]["slug"] == catalog.leaf.slug
    assert {row["id"] for row in brands.json()["items"]} >= {str(catalog.brand.id)}
    assert len(brands_page.json()["items"]) == 1
    assert brands_page.json()["has_more"] is True


async def test_filters_combine_category_brand_price_stock_and_specs(
    client: httpx.AsyncClient, catalog: Catalog
) -> None:
    params = [
        ("category_slug", catalog.root.slug),
        ("brand_id", str(catalog.brand.id)),
        ("min_price", "79999.90"),
        ("max_price", "79999.90"),
        ("in_stock", "true"),
        ("spec", "ram_gb:gte:32"),
        ("spec", "os:eq:Linux"),
    ]
    response = await client.get("products", params=params)

    assert response.status_code == 200
    items = response.json()["items"]
    assert [item["id"] for item in items] == [str(catalog.products["alpha"].id)]
    assert items[0]["price"] == "79999.90"
    assert items[0]["brand"]["id"] == str(catalog.brand.id)


async def test_currency_pagination_and_stable_price_order(
    client: httpx.AsyncClient, catalog: Catalog
) -> None:
    product_ids = sorted(str(catalog.products[name].id) for name in ("alpha", "gamma"))
    params = {
        "category_id": str(catalog.root.id),
        "sort": "price_asc",
        "in_stock": True,
        "limit": 1,
    }
    first = await client.get("products", params=params)
    next_page = await client.get("products", params={**params, "offset": 1})
    empty = await client.get("products", params={**params, "offset": 2})
    usd = await client.get("products", params={**params, "currency": "USD", "max_price": "950"})
    unavailable = await client.get(
        "products", params={"category_id": str(catalog.root.id), "in_stock": False}
    )

    assert first.json()["items"][0]["id"] == product_ids[0]
    assert first.json()["has_more"] is True
    assert next_page.json()["items"][0]["id"] == product_ids[1]
    assert next_page.json()["has_more"] is False
    assert empty.json() == {"items": [], "limit": 1, "offset": 2, "has_more": False}
    assert [item["id"] for item in usd.json()["items"]] == [str(catalog.products["import"].id)]
    assert [item["id"] for item in unavailable.json()["items"]] == [
        str(catalog.products["beta"].id)
    ]


async def test_numeric_spec_filters_handle_preexisting_non_numeric_values(
    client: httpx.AsyncClient, catalog: Catalog
) -> None:
    for condition in ("depth_mm:lte:200", "depth_mm:eq:200.0"):
        response = await client.get(
            "products", params={"category_id": str(catalog.root.id), "spec": condition}
        )
        assert response.status_code == 200
        assert [item["id"] for item in response.json()["items"]] == [
            str(catalog.products["alpha"].id)
        ]


async def test_card_specifications_and_ordered_comparison(
    client: httpx.AsyncClient, catalog: Catalog
) -> None:
    alpha = str(catalog.products["alpha"].id)
    beta = str(catalog.products["beta"].id)
    details = await client.get(f"products/{alpha}")
    specs = await client.get(f"products/{alpha}/specifications")
    comparison = await client.post("products/compare", json={"product_ids": [beta, alpha]})

    assert details.status_code == specs.status_code == comparison.status_code == 200
    assert details.json()["description"] == "Техническое описание модели."
    assert details.json()["category"]["slug"] == catalog.leaf.slug
    assert specs.json() == {"product_id": alpha, "specifications": details.json()["specifications"]}
    assert [item["id"] for item in comparison.json()["products"]] == [beta, alpha]
    assert comparison.json()["specifications"]["ram_gb"] == [16, 32]
    assert comparison.json()["specifications"]["ssd_gb"] == [512, None]


async def test_missing_and_inactive_products_are_unavailable(
    client: httpx.AsyncClient, catalog: Catalog
) -> None:
    hidden = str(catalog.products["hidden"].id)
    available = str(catalog.products["alpha"].id)
    assert (await client.get(f"products/{uuid4()}")).status_code == 404
    assert (await client.get(f"products/{hidden}")).status_code == 404
    assert (await client.get(f"products/{hidden}/specifications")).status_code == 404

    comparison = await client.post("products/compare", json={"product_ids": [available, hidden]})
    assert comparison.status_code == 404
    assert comparison.json() == {"detail": "Один или несколько товаров не найдены."}


@pytest.mark.parametrize(
    "params",
    [
        {"limit": 101},
        {"offset": -1},
        {"min_price": 200, "max_price": 100},
        {"max_price": "NaN"},
        {"spec": "ram_gb:gte:много"},
        {"spec": "os:gte:Linux"},
        {"spec": "unsupported:eq:1"},
        {"sort": "popularity"},
        {"unknown": "value"},
    ],
)
async def test_rejects_invalid_product_query(
    client: httpx.AsyncClient, params: dict[str, object]
) -> None:
    assert (await client.get("products", params=params)).status_code == 422


async def test_compare_rejects_duplicate_or_missing_arguments(client: httpx.AsyncClient) -> None:
    product_id = str(uuid4())
    for ids in ([], [product_id], [product_id, product_id], [str(uuid4()) for _ in range(6)]):
        result = await client.post("products/compare", json={"product_ids": ids})
        assert result.status_code == 422
    assert (await client.get("products/no-such-id")).status_code == 422
