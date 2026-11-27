from dataclasses import dataclass
from decimal import Decimal
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.retrieval.keyword import (
    document_keyword_statement,
    product_keyword_statement,
    search_documents_by_keywords,
    search_products_by_keywords,
)
from app.modules.catalog.models import Brand, Category, DocumentType, Product, ProductDocument
from app.modules.catalog.schemas import ProductFilters

pytestmark = pytest.mark.asyncio


@dataclass
class KeywordCatalog:
    root: Category
    products: dict[str, Product]
    documents: dict[str, ProductDocument]
    filters: ProductFilters


@pytest_asyncio.fixture
async def keyword_catalog(session: AsyncSession) -> KeywordCatalog:
    suffix = uuid4().hex
    root = Category(name="Компьютеры", slug=f"keyword-{suffix}", description="")
    category = Category(name="Ноутбуки", slug=f"laptops-{suffix}", description="", parent=root)
    brand = Brand(name=f"Альта {suffix}", description="")
    exact_sku = f"FT-{suffix}-042"
    products = {}
    documents = {}
    variants = {
        "main": ("Игровой ноутбук Альта V15-4060", exact_sku, 80_000, 2, 32, True),
        "mention": ("Рабочая станция Альта", f"{suffix}-mention", 75_000, 1, 16, True),
        "sku-variant": ("OLED монитор", f"FT{suffix}042", 65_000, 2, 16, True),
        "over-budget": ("Профессиональный ноутбук", f"{suffix}-cost", 80_001, 3, 32, True),
        "out-of-stock": ("Игровой ноутбук", f"{suffix}-empty", 72_000, 0, 32, True),
        "low-ram": ("Ноутбук для учёбы", f"{suffix}-ram", 32_000, 2, 8, True),
        "inactive": ("Ноутбук архивный", f"{suffix}-inactive", 32_000, 2, 32, False),
    }
    for label, (name, sku, price, stock, ram, active) in variants.items():
        product = Product(
            category=category,
            brand=brand,
            name=name,
            sku=sku,
            description=(
                f"Комплект для ноутбука {exact_sku}."
                if label == "mention"
                else "Обновлённое охлаждение."
            ),
            price=Decimal(price),
            stock_quantity=stock,
            is_active=active,
            specifications={"ram_gb": ram, "gpu": "RTX-4060"}
            if label != "sku-variant"
            else {"ram_gb": ram},
        )
        products[label] = product
        session.add(product)
        if label == "sku-variant":
            continue
        document = ProductDocument(
            product=product,
            document_type=DocumentType.TECHNICAL_SPECIFICATION
            if label == "mention"
            else DocumentType.PRODUCT_MANUAL,
            title="Настройка драйвера RTX-4060" if label != "mention" else "Список компонентов",
            content="Драйвер поддерживает графический модуль RTX-4060."
            if label == "mention"
            else "Подключите адаптер.",
            source=f"catalog/{label}",
        )
        documents[label] = document
        session.add(document)
    await session.flush()
    return KeywordCatalog(
        root,
        products,
        documents,
        ProductFilters(
            category_id=root.id,
            max_price=Decimal("80000"),
            in_stock=True,
            spec=["ram_gb:gte:16"],
        ),
    )


async def test_russian_inflection_rank_and_mandatory_filters(
    session: AsyncSession,
    keyword_catalog: KeywordCatalog,
) -> None:
    matches = await search_products_by_keywords(
        session, "ноутбуком", filters=keyword_catalog.filters
    )
    assert [match.product_id for match in matches] == [
        keyword_catalog.products["main"].id,
        keyword_catalog.products["mention"].id,
    ]
    assert 0 < matches[1].score < matches[0].score < 1


async def test_exact_sku_precedes_normalized_and_text_matches(
    session: AsyncSession,
    keyword_catalog: KeywordCatalog,
) -> None:
    sku = keyword_catalog.products["main"].sku
    exact = await search_products_by_keywords(session, sku.lower(), filters=keyword_catalog.filters)
    assert [(match.product_id, match.score) for match in exact[:2]] == [
        (keyword_catalog.products["main"].id, 2.0),
        (keyword_catalog.products["sku-variant"].id, 1.0),
    ]
    assert exact[2].product_id == keyword_catalog.products["mention"].id

    typed_with_spaces = await search_products_by_keywords(
        session, sku.replace("-", " "), filters=keyword_catalog.filters
    )
    assert {match.product_id for match in typed_with_spaces if match.score >= 1} == {
        keyword_catalog.products[label].id for label in ("main", "sku-variant")
    }

    top = await search_products_by_keywords(session, sku, filters=keyword_catalog.filters, top_k=1)
    assert top[0].product_id == keyword_catalog.products["main"].id


async def test_search_accepts_model_names_and_technical_terms(
    session: AsyncSession,
    keyword_catalog: KeywordCatalog,
) -> None:
    expected = keyword_catalog.products["main"].id
    for query in ("Альта V15‑4060", "RTX‑4060 ОБНОВЛЕННОЕ"):
        matches = await search_products_by_keywords(session, query, filters=keyword_catalog.filters)
        assert [match.product_id for match in matches] == [expected]
    terms = await search_products_by_keywords(session, "RTX-4060", filters=keyword_catalog.filters)
    assert {match.product_id for match in terms} == {
        keyword_catalog.products[key].id for key in ("main", "mention")
    }


async def test_document_rank_filters_and_source_references(
    session: AsyncSession,
    keyword_catalog: KeywordCatalog,
) -> None:
    matches = await search_documents_by_keywords(
        session, "драйвером", filters=keyword_catalog.filters
    )
    assert [match.document_id for match in matches] == [
        keyword_catalog.documents[label].id for label in ("main", "mention")
    ]
    assert matches[0].score > matches[1].score
    assert matches[0].product_id == keyword_catalog.products["main"].id
    assert matches[0].source == "catalog/main"
    only_manuals = await search_documents_by_keywords(
        session,
        "RTX-4060",
        filters=keyword_catalog.filters,
        document_type=DocumentType.PRODUCT_MANUAL,
    )
    assert [match.document_id for match in only_manuals] == [keyword_catalog.documents["main"].id]


async def test_search_columns_refresh_on_product_and_document_edits(
    session: AsyncSession,
    keyword_catalog: KeywordCatalog,
) -> None:
    product = keyword_catalog.products["main"]
    document = keyword_catalog.documents["main"]
    new_sku = f"NEW-{uuid4().hex}"
    await session.execute(
        update(Product).where(Product.id == product.id).values(sku=new_sku, name="Ноутбук Зенит")
    )
    await session.execute(
        update(ProductDocument)
        .where(ProductDocument.id == document.id)
        .values(
            title="Установка прошивки",
            content="Включите устройство.",
        )
    )

    exact = await search_products_by_keywords(session, new_sku, filters=keyword_catalog.filters)
    assert exact[0].product_id == product.id and exact[0].score == 2.0
    assert (
        await search_products_by_keywords(session, "V15-4060", filters=keyword_catalog.filters)
        == []
    )
    updated = await search_documents_by_keywords(
        session, "прошивку", filters=keyword_catalog.filters
    )
    assert [match.document_id for match in updated] == [document.id]


async def test_punctuation_and_russian_stopwords_return_no_matches(
    session: AsyncSession,
    keyword_catalog: KeywordCatalog,
) -> None:
    for query in ("?!…", "и на в"):
        assert (
            await search_products_by_keywords(session, query, filters=keyword_catalog.filters) == []
        )
        assert (
            await search_documents_by_keywords(session, query, filters=keyword_catalog.filters)
            == []
        )


async def test_postgres_uses_fts_and_sku_indexes(
    session: AsyncSession,
    keyword_catalog: KeywordCatalog,
) -> None:
    await session.execute(text("SET LOCAL enable_seqscan = off"))
    connection = await session.connection()
    statements = (
        (
            product_keyword_statement(keyword_catalog.products["main"].sku, ProductFilters(), 5),
            ("ix_products_search_vector", "ix_products_search_sku"),
        ),
        (
            document_keyword_statement("драйвер", ProductFilters(), None, 5),
            ("ix_product_documents_search_vector",),
        ),
    )
    for statement, indexes in statements:
        sql = statement.compile(dialect=connection.dialect, compile_kwargs={"literal_binds": True})
        plan = "\n".join((await connection.exec_driver_sql(f"EXPLAIN (COSTS OFF) {sql}")).scalars())
        assert all(index in plan for index in indexes), plan
