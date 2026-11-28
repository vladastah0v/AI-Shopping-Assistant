import re
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.ai.intent import Intent, IntentQuery
from app.modules.catalog.schemas import ProductFilters


class SessionMemory(BaseModel):
    filters: ProductFilters = Field(default_factory=ProductFilters)
    query: str = Field(default="", max_length=512)
    use_case: str | None = Field(default=None, max_length=100)
    preference: Literal["cheaper", "similar"] | None = None
    product_ids: list[UUID] = Field(default_factory=list, max_length=10)


_ORDINALS = re.compile(r"\b(перв[а-я]+|втор[а-я]+|трет[а-я]+|четв[её]рт[а-я]+|пят[а-я]+)\b", re.I)
_ORDINAL_PREFIXES = ("перв", "втор", "трет", "четв", "пят")
_UUID = re.compile(r"\b[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\b", re.I)
LOOKUP_INTENTS = {
    Intent.PRODUCT_COMPARISON,
    Intent.PRODUCT_INFORMATION,
    Intent.PRICE_CHECK,
    Intent.STOCK_CHECK,
}


def referenced_products(message: str, request: IntentQuery, state: SessionMemory) -> list[UUID]:
    explicit = list(dict.fromkeys(UUID(match) for match in _UUID.findall(message)))[:5]
    if explicit:
        return explicit
    if request.intent not in LOOKUP_INTENTS and request.alternative is None:
        return []
    positions = [
        next(
            index
            for index, prefix in enumerate(_ORDINAL_PREFIXES)
            if word.lower().startswith(prefix)
        )
        for word in _ORDINALS.findall(message)
    ]
    if positions:
        if max(positions) >= len(state.product_ids):
            return []
        return list(dict.fromkeys(state.product_ids[index] for index in positions))[:5]
    if request.alternative is not None:
        return state.product_ids[:1]
    if request.intent == Intent.PRODUCT_COMPARISON:
        return []
    return state.product_ids[:5]


def merge_intent(request: IntentQuery, state: SessionMemory) -> IntentQuery:
    if request.intent in (
        Intent.GENERAL_CONVERSATION,
        Intent.UNSUPPORTED_REQUEST,
        Intent.CLARIFICATION,
    ):
        return request
    old = state.filters.model_dump(exclude_none=True, exclude_defaults=True)
    new = request.filters.model_dump(exclude_none=True, exclude_defaults=True)
    category_keys = {"category_id", "category_slug"}
    changes_category = any(key in new and old.get(key) != new[key] for key in category_keys)
    if changes_category:
        for key in (*category_keys, "spec", "brand_id"):
            old.pop(key, None)
    if "spec" in new:
        updated_keys = {item.key for item in request.filters.specification_filters}
        new["spec"] = [
            raw for raw in old.get("spec", []) if raw.split(":", 1)[0] not in updated_keys
        ] + new["spec"]
    has_followup_filters = bool(new) and not changes_category and request.use_case is None
    inherit_query = has_followup_filters or request.alternative is not None
    query = state.query if inherit_query else request.query
    return request.model_copy(
        update={
            "filters": ProductFilters.model_validate(old | new),
            "query": query,
            "use_case": request.use_case or (state.use_case if not changes_category else None),
        }
    )
