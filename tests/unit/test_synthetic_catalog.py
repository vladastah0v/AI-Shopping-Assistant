from decimal import Decimal
from itertools import islice

import pytest
from pydantic import ValidationError

from app.modules.catalog.admin import ProductInput
from app.modules.catalog.models import NUMERIC_SPECIFICATION_KEYS, DocumentType
from app.modules.catalog.synthetic import DEFAULT_SEED, PROFILE_SIZES, generate_products
from app.modules.catalog.synthetic_presets import BRAND_NAMES, CATEGORIES, ROOT_CATEGORIES


def test_seed_reproduces_ids_content_and_profile_prefix() -> None:
    small = list(generate_products(PROFILE_SIZES["small"], DEFAULT_SEED))
    medium_prefix = list(islice(generate_products(PROFILE_SIZES["medium"], DEFAULT_SEED), 100))
    other_seed = list(generate_products(100, DEFAULT_SEED + 1))

    assert PROFILE_SIZES == {"small": 100, "medium": 1000, "large": 10_000}
    assert len(small) == 100
    assert small == medium_prefix
    assert len({product.values["id"] for product in small}) == 100
    assert {p.values["sku"] for p in small}.isdisjoint(p.values["sku"] for p in other_seed)


def test_synthetic_documents_and_specs_match_their_products() -> None:
    products = list(generate_products(100, DEFAULT_SEED))

    assert len(CATEGORIES) + len(ROOT_CATEGORIES) == 13
    assert {p.category_slug for p in products} == {category.slug for category in CATEGORIES}
    assert {p.brand_name for p in products} == set(BRAND_NAMES)
    assert len(BRAND_NAMES) == 24
    assert any(p.values["stock_quantity"] == 0 for p in products)
    assert any(p.values["stock_quantity"] > 0 for p in products)

    for product in products:
        assert isinstance(product.values["price"], Decimal)
        specifications = product.values["specifications"]
        assert all(
            type(specifications[key]) in (int, float) and specifications[key] > 0
            for key in specifications.keys() & set(NUMERIC_SPECIFICATION_KEYS)
        )
        if product.category_slug == "refrigerators":
            assert specifications["freezer_volume_l"] < specifications["volume_l"]
        if product.category_slug == "computers" and "vram_gb" in specifications:
            assert specifications["power_w"] >= 650 and specifications["ram_gb"] >= 32
        assert {doc["document_type"] for doc in product.documents} == set(DocumentType)
        assert all(doc["product_id"] == product.values["id"] for doc in product.documents)


@pytest.mark.parametrize(
    "change",
    [
        {"price": "49999.001"},
        {"stock_quantity": -1},
        {"specifications": {"ram_gb": "16"}},
        {"specifications": {"ram_gb": True}},
        {"is_active": "false"},
    ],
)
def test_admin_input_rejects_invalid_values(change: dict[str, object]) -> None:
    valid = {
        "name": "Тестовый ноутбук",
        "category_slug": "laptops",
        "brand_name": "Вымышленный бренд",
        "description": "Ноутбук для работы",
        "price": "49999.90",
    }
    with pytest.raises(ValidationError):
        ProductInput.model_validate(valid | change)
