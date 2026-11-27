from dataclasses import dataclass
from itertools import batched
from typing import Any
from uuid import UUID, uuid5

from sqlalchemy import Table, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.models import Brand, Category, Product, ProductDocument
from app.modules.catalog.synthetic import (
    CATALOG_NAMESPACE,
    MAX_SEED,
    PROFILE_SIZES,
    generate_products,
)
from app.modules.catalog.synthetic_presets import BRAND_NAMES, CATEGORIES, ROOT_CATEGORIES


@dataclass(slots=True)
class SeedResult:
    categories: int = 0
    brands: int = 0
    products: int = 0
    documents: int = 0


async def seed_catalog(session: AsyncSession, profile: str, seed: int) -> SeedResult:
    if not 0 <= seed <= MAX_SEED:
        raise ValueError(f"Seed должен быть целым числом от 0 до {MAX_SEED}.")
    product_count = PROFILE_SIZES[profile]
    categories = Category.__table__
    brands = Brand.__table__
    products = Product.__table__
    documents = ProductDocument.__table__
    result = SeedResult()

    result.categories += await _insert_missing(
        session,
        categories,
        "slug",
        [_category_row(slug, name, None) for slug, name in ROOT_CATEGORIES.items()],
    )
    root_ids = await _ids_by_value(session, categories, "slug", list(ROOT_CATEGORIES))
    result.categories += await _insert_missing(
        session,
        categories,
        "slug",
        [
            _category_row(template.slug, template.name, root_ids[template.parent_slug])
            for template in CATEGORIES
        ],
    )
    category_ids = await _ids_by_value(session, categories, "slug", [t.slug for t in CATEGORIES])

    result.brands = await _insert_missing(
        session,
        brands,
        "name",
        [
            {
                "id": uuid5(CATALOG_NAMESPACE, f"brand:{name}"),
                "name": name,
                "description": f"{name} — производитель электроники и бытовой техники.",
            }
            for name in BRAND_NAMES
        ],
    )
    brand_ids = await _ids_by_value(session, brands, "name", list(BRAND_NAMES))

    for batch in batched(generate_products(product_count, seed), 100):
        product_rows = [
            {
                **product.values,
                "category_id": category_ids[product.category_slug],
                "brand_id": brand_ids[product.brand_name],
            }
            for product in batch
        ]
        result.products += await _insert_missing(session, products, "sku", product_rows)
        existing_ids = await _ids_by_value(
            session, products, "sku", [row["sku"] for row in product_rows]
        )
        for row in product_rows:
            if existing_ids.get(row["sku"]) != row["id"]:
                raise ValueError(f"Артикул {row['sku']} уже принадлежит другой записи каталога.")

        document_rows = [document for product in batch for document in product.documents]
        result.documents += await _insert_missing(session, documents, "id", document_rows)

    return result


def _category_row(slug: str, name: str, parent_id: UUID | None) -> dict[str, Any]:
    return {
        "id": uuid5(CATALOG_NAMESPACE, f"category:{slug}"),
        "slug": slug,
        "name": name,
        "description": f"Раздел каталога «{name}».",
        "parent_id": parent_id,
    }


async def _insert_missing(
    session: AsyncSession, table: Table, key: str, rows: list[dict[str, Any]]
) -> int:
    statement = insert(table).values(rows).on_conflict_do_nothing(index_elements=[key])
    return len((await session.scalars(statement.returning(table.c.id))).all())


async def _ids_by_value(
    session: AsyncSession, table: Table, key: str, values: list[str]
) -> dict[str, UUID]:
    column = table.c[key]
    statement = (
        select(column, table.c.id)
        .where(column.in_(values))
        .with_for_update(read=True, key_share=True)
    )
    return dict((await session.execute(statement)).all())
