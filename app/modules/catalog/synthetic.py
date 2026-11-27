from collections.abc import Iterator
from dataclasses import dataclass
from decimal import Decimal
from random import Random
from typing import Any
from uuid import UUID, uuid5

from app.modules.catalog.models import DocumentType
from app.modules.catalog.synthetic_presets import BRAND_NAMES, CATEGORIES, SpecificationValue

CATALOG_NAMESPACE = UUID("d48c2b5e-4895-4b6c-8872-d898932bc581")
PROFILE_SIZES = {"small": 100, "medium": 1000, "large": 10_000}
DEFAULT_SEED = 42
MAX_SEED = 2**64 - 1

_SPECIFICATION_LABELS = {
    "cpu": "Процессор",
    "gpu": "Графика",
    "ram_gb": "Оперативная память, ГБ",
    "ssd_gb": "SSD, ГБ",
    "storage_gb": "Память, ГБ",
    "vram_gb": "Видеопамять, ГБ",
    "display_size_in": "Диагональ, дюймы",
    "resolution_width_px": "Ширина экрана, пиксели",
    "resolution_height_px": "Высота экрана, пиксели",
    "refresh_rate_hz": "Частота обновления, Гц",
    "battery_capacity_mah": "Ёмкость аккумулятора, мА·ч",
    "camera_mp": "Основная камера, Мп",
    "weight_g": "Масса, г",
    "volume_l": "Объём, л",
    "load_capacity_kg": "Загрузка, кг",
    "power_w": "Мощность, Вт",
    "os": "Операционная система",
    "panel": "Тип панели",
    "connection": "Подключение",
    "form_factor": "Конструкция",
    "noise_cancellation": "Шумоподавление",
    "component_type": "Тип комплектующего",
    "interface": "Интерфейс",
    "freezer_volume_l": "Объём морозильной камеры, л",
    "defrost_type": "Система размораживания",
    "spin_speed_rpm": "Скорость отжима, об/мин",
    "depth_mm": "Глубина, мм",
    "appliance_type": "Тип прибора",
}


@dataclass(frozen=True, slots=True)
class GeneratedProduct:
    category_slug: str
    brand_name: str
    values: dict[str, Any]
    documents: list[dict[str, Any]]


def generate_products(count: int, seed: int) -> Iterator[GeneratedProduct]:
    rng = Random(seed)
    brands = list(BRAND_NAMES)
    rng.shuffle(brands)

    for index in range(count):
        category = CATEGORIES[index % len(CATEGORIES)]
        brand = brands[index % len(brands)]
        preset = rng.choice(category.presets)
        specifications = {
            key: rng.choice(value) if isinstance(value, tuple) else value
            for key, value in preset.specifications.items()
        }
        sku = f"SYN-{seed:X}-{index + 1:05d}"
        product_id = uuid5(CATALOG_NAMESPACE, sku)
        name = f"{brand} {category.series}-{index + 1:05d} {preset.edition}"
        description = f"{name} — модель для {preset.purpose}."
        price = Decimal(rng.randrange(*preset.price_range, 100)) - Decimal("0.10")
        rating = None if rng.randrange(6) == 0 else Decimal(rng.randint(360, 500)).scaleb(-2)

        yield GeneratedProduct(
            category_slug=category.slug,
            brand_name=brand,
            values={
                "id": product_id,
                "sku": sku,
                "name": name,
                "description": description,
                "price": price,
                "currency": "RUB",
                "stock_quantity": rng.choice((0, 0, 2, 4, 8, 12, 20, 35)),
                "rating": rating,
                "is_active": True,
                "specifications": specifications,
            },
            documents=_documents(
                product_id, sku, name, description, specifications, category.setup
            ),
        )


def _documents(
    product_id: UUID,
    sku: str,
    name: str,
    description: str,
    specifications: dict[str, SpecificationValue],
    setup: str,
) -> list[dict[str, Any]]:
    features = "\n".join(
        f"{_SPECIFICATION_LABELS[key]} — {value}" for key, value in specifications.items()
    )
    documents = {
        DocumentType.PRODUCT_DESCRIPTION: (f"Описание {name}", description),
        DocumentType.TECHNICAL_SPECIFICATION: (f"Характеристики {name}", features),
        DocumentType.PRODUCT_MANUAL: (f"Первое использование {name}", setup),
        DocumentType.FREQUENTLY_ASKED_QUESTIONS: (
            f"Частые вопросы о {name}",
            f"Для чего подходит модель?\n{description}\n\nКак начать работу?\n{setup}",
        ),
    }
    return [
        {
            "id": uuid5(product_id, kind.value),
            "product_id": product_id,
            "document_type": kind,
            "title": title,
            "content": content,
            "source": f"catalog://synthetic/{sku}/{kind.value}",
        }
        for kind, (title, content) in documents.items()
    ]
