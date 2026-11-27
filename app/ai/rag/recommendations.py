from collections.abc import Sequence

from app.ai.intent import IntentQuery
from app.ai.rag.schemas import Recommendation
from app.modules.catalog.schemas import ProductRead

_TECHNICAL_FIELDS = {
    "laptops": ("ram_gb", "ssd_gb", "battery_capacity_mah"),
    "computers": ("ram_gb", "ssd_gb"),
    "smartphones": ("storage_gb", "ram_gb", "battery_capacity_mah"),
    "tablets": ("storage_gb", "ram_gb", "battery_capacity_mah"),
    "monitors": ("refresh_rate_hz", "resolution_width_px", "resolution_height_px"),
    "televisions": ("refresh_rate_hz", "resolution_width_px", "resolution_height_px"),
    "refrigerators": ("volume_l", "freezer_volume_l"),
    "washing-machines": ("wash_capacity_kg",),
}


def _value(product: ProductRead, key: str) -> float:
    value = product.specifications.get(key)
    return float(value) if type(value) in (int, float) and value > 0 else 0


def recommend(request: IntentQuery, candidates: Sequence[ProductRead]) -> list[Recommendation]:
    if not candidates:
        return []
    ordered = sorted(candidates, key=lambda item: item.stock_quantity == 0)
    preferred = ordered[0]
    if request.alternative is not None:
        return [
            Recommendation(
                product_id=product.id,
                kind="alternative",
                reason="Более доступный вариант с указанными условиями."
                if request.alternative == "cheaper"
                else "Другой товар с указанными характеристиками.",
            )
            for product in ordered[:3]
        ]
    output = [
        Recommendation(
            product_id=preferred.id,
            kind="optimal",
            reason="Первый по релевантности среди товаров с учётом наличия.",
        )
    ]
    currency = request.filters.price_currency or preferred.currency
    budget = min(
        (item for item in ordered if item.currency == currency and item.id != preferred.id),
        key=lambda item: item.price,
        default=None,
    )
    if budget is not None and budget.price <= preferred.price:
        output.append(
            Recommendation(
                product_id=budget.id,
                kind="budget",
                reason="Наименьшая цена среди остальных подходящих товаров в этой валюте.",
            )
        )
    selected_ids = {item.product_id for item in output}
    same_category = [item for item in ordered if item.category.id == preferred.category.id]
    fields = _TECHNICAL_FIELDS.get(preferred.category.slug, ())
    maxima = {key: max(_value(item, key) for item in same_category) for key in fields}
    scores = {
        item.id: sum(_value(item, key) / maximum for key, maximum in maxima.items() if maximum)
        for item in same_category
    }
    best = max(
        (item for item in same_category if item.id not in selected_ids),
        key=lambda item: scores[item.id],
        default=None,
    )
    if best is not None and scores[best.id] > max(scores.get(key, 0) for key in selected_ids):
        output.append(
            Recommendation(
                product_id=best.id,
                kind="specifications",
                reason="Более высокие значения сравнимых характеристик в этой категории.",
            )
        )
    return output
