from decimal import Decimal

import pytest

from app.ai.intent import Intent, IntentResolver, infer_intent
from app.ai.llm.provider import LLMUnavailable


def test_extracts_constraints_and_catalog_codes() -> None:
    request = infer_intent(
        "Подбери ноутбук для программирования до 80 000 рублей с 32 ГБ ОЗУ и SSD 1 ТБ"
    )
    assert request.intent == Intent.RECOMMENDATION
    assert request.filters.category_slug == "laptops"
    assert request.filters.max_price == Decimal("80000")
    assert request.filters.spec == ["ram_gb:gte:32", "ssd_gb:gte:1024"]
    assert request.query == "программирование"
    television = infer_intent("Найди телевизор 55 дюймов в наличии")
    assert television.filters.category_slug == "televisions"
    assert television.filters.spec == ["display_size_in:eq:55"]
    assert television.filters.in_stock is True
    assert infer_intent("Подбери ноутбук до 32 ГБ памяти").filters.max_price is None


class StubLLM:
    def __init__(self, text):
        self.text = text
        self.calls = []

    async def generate(self, messages, *, schema=None):
        self.calls.append((messages, schema))
        if self.text is None:
            raise LLMUnavailable()
        return self.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "output", ['{"intent":"product_search","filters":{"max_price":120000}}', "{", None]
)
async def test_chain_validates_structure_and_preserves_explicit_budget(output) -> None:
    provider = StubLLM(output)
    request = await IntentResolver(provider).resolve("Найди ноутбук до 80 тыс.")
    assert request.filters.category_slug == "laptops"
    assert request.filters.max_price == 80_000
    messages, schema = provider.calls[0]
    assert messages[0].role == "system"
    assert messages[1].content == "Найди ноутбук до 80 тыс."
    assert "filters" in schema["properties"]


def test_relative_ram_request_keeps_alternative_intent() -> None:
    request = infer_intent("Есть такой же ноутбук, но с большей оперативной памятью?")
    assert request.intent == Intent.RECOMMENDATION
    assert request.alternative == "similar"
    assert request.more_ram
