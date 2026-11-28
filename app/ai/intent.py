from __future__ import annotations

import re
from decimal import Decimal, localcontext
from enum import StrEnum
from typing import TYPE_CHECKING, Annotated, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
)

from app.ai.guardrails import suspicious_instruction
from app.ai.llm.provider import ChatMessage, LLMError, LLMProvider
from app.core.http import validate_public_text
from app.modules.catalog.schemas import ProductFilters

if TYPE_CHECKING:
    from langchain_core.prompt_values import ChatPromptValue


class Intent(StrEnum):
    PRODUCT_SEARCH = "product_search"
    PRODUCT_COMPARISON = "product_comparison"
    PRODUCT_INFORMATION = "product_information"
    STOCK_CHECK = "stock_check"
    PRICE_CHECK = "price_check"
    RECOMMENDATION = "recommendation"
    CLARIFICATION = "clarification"
    GENERAL_CONVERSATION = "general_conversation"
    UNSUPPORTED_REQUEST = "unsupported_request"


class IntentQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent: Intent
    query: Annotated[
        str,
        StringConstraints(strip_whitespace=True, max_length=512),
        AfterValidator(validate_public_text),
    ] = ""
    filters: ProductFilters = Field(default_factory=ProductFilters)
    use_case: str | None = Field(default=None, max_length=100)
    alternative: Literal["cheaper", "similar"] | None = None
    more_ram: bool = False


_NUMBER = r"(?:\d{1,3}(?:[ _]\d{3})+|\d+)(?:[.,]\d+)?"
_BUDGET = re.compile(
    rf"(?:\bдо\s+|не дороже\s+|бюджет\s*(?:до\s+)?)(?P<amount>{_NUMBER})"
    rf"\s*(?P<thousand>тыс(?:яч[а-я]*)?\.?)?(?![\d.,]|\s*(?:гб|тб|дюйм))"
)
_SPECS = (
    ("ram_gb", re.compile(rf"(?P<amount>{_NUMBER})\s*гб\s*(?:оператив|озу)")),
    ("ram_gb", re.compile(rf"(?:озу|оперативн[а-я]*\s+памят[а-я]*)\s+(?P<amount>{_NUMBER})\s*гб")),
    ("ssd_gb", re.compile(rf"(?P<amount>{_NUMBER})\s*(?P<tb>тб|гб)\s*(?:ssd|накопител)")),
    ("ssd_gb", re.compile(rf"(?:ssd|накопител[а-я]*)\s+(?P<amount>{_NUMBER})\s*(?P<tb>тб|гб)")),
    ("display_size_in", re.compile(rf"(?P<amount>{_NUMBER})\s*(?:дюйм|″)")),
)
_MAXIMUM_QUALIFIER = re.compile(r"\b(?:до|не более|не больше|не выше|максимум)\s*$")
_MORE_RAM = re.compile(
    r"(?<!не )\b(?:больше|большей|большим|побольше)(?:\s+\w+){0,2}\s+(?:оперативн|озу\b|ram\b)"
    r"|\b(?:озу|ram)\s+(?:нужно\s+)?(?:больше|побольше)\b"
)
_CATEGORIES = (
    ("laptops", r"ноутбук"),
    ("smartphones", r"смартфон|телефон"),
    ("televisions", r"телевизор"),
    ("tablets", r"планшет"),
    ("monitors", r"монитор"),
    ("computers", r"компьютер|системн[а-я]* блок"),
    ("headphones", r"наушник|гарнитур"),
    ("gaming-components", r"комплектующ|видеокарт|материнск"),
    ("refrigerators", r"холодильник|морозильник"),
    ("washing-machines", r"стиральн|стиралк"),
    ("small-appliances", r"блендер|чайник|миксер|кофемашин|мультиварк|пылесос"),
)
_PURPOSES = (
    ("программирование", r"программир|разработ[кч]"),
    ("игры", r"игр[а-я]*|гейм"),
    ("фотография", r"фотограф|съемк"),
    ("учёба", r"учеб|студен"),
    ("документы", r"документ"),
    ("офис", r"офис"),
    ("видеомонтаж", r"монтаж"),
)
_INTENT_RULES = (
    (Intent.PRODUCT_COMPARISON, r"сравн|отлича"),
    (Intent.STOCK_CHECK, r"наличии|остаток|на складе"),
    (Intent.PRICE_CHECK, r"сколько стоит|какая цена|стоимость"),
    (Intent.PRODUCT_INFORMATION, r"характеристик|расскажи о|инструкция"),
    (Intent.RECOMMENDATION, r"подбери|посоветуй|рекоменд|подходит|вариант|подешевле|дешевле"),
    (Intent.PRODUCT_SEARCH, r"найди|покажи|ищу|нужен|нужна"),
    (Intent.GENERAL_CONVERSATION, r"^(?:привет|спасибо|здравствуйте|добрый день)[!. ]*$"),
)


def _amount(value: str) -> Decimal:
    return Decimal(value.replace(" ", "").replace("_", "").replace(",", "."))


def infer_intent(message: str) -> IntentQuery:
    normalized = " ".join(message.lower().replace("ё", "е").split())
    category = next((slug for slug, pattern in _CATEGORIES if re.search(pattern, normalized)), None)
    purpose = next((name for name, pattern in _PURPOSES if re.search(pattern, normalized)), None)
    intent = next(
        (name for name, pattern in _INTENT_RULES if re.search(pattern, normalized)),
        Intent.PRODUCT_SEARCH if category else Intent.CLARIFICATION,
    )
    filters: dict = {"category_slug": category}
    budget = _BUDGET.search(normalized)
    if budget:
        with localcontext() as precision:
            precision.prec = 24
            maximum = _amount(budget["amount"]) * (1000 if budget["thousand"] else 1)
        filters.update(max_price=maximum, currency="RUB")
    if re.search(
        r"\b(?:только в наличии|имеется в наличии|есть в наличии|в наличии|на складе)\b", normalized
    ):
        filters["in_stock"] = True
    specs = []
    for key, pattern in _SPECS:
        if match := pattern.search(normalized):
            value = _amount(match["amount"]) * (1024 if match.groupdict().get("tb") == "тб" else 1)
            operator = "eq" if key == "display_size_in" else "gte"
            if _MAXIMUM_QUALIFIER.search(normalized[: match.start("amount")]):
                operator = "lte"
            specs.append(f"{key}:{operator}:{value:f}")
    filters["spec"] = list(dict.fromkeys(specs))
    if intent == Intent.CLARIFICATION and (budget or specs):
        intent = Intent.PRODUCT_SEARCH
    try:
        constraints = ProductFilters.model_validate(filters)
    except (ValidationError, ArithmeticError):
        return IntentQuery(intent=Intent.CLARIFICATION)
    query = purpose or (message.strip()[:512] if category is None else "")
    alternative = None
    if re.search(r"дешевле|подешевле|менее дорог", normalized):
        alternative = "cheaper"
    more_ram = _MORE_RAM.search(normalized) is not None
    if alternative is None and (
        more_ram or re.search(r"альтернатив|похож|такой же|такая же", normalized)
    ):
        alternative = "similar"
    return IntentQuery(
        intent=Intent.RECOMMENDATION if more_ram else intent,
        query=query,
        filters=constraints,
        use_case=purpose,
        alternative=alternative,
        more_ram=more_ram,
    )


class IntentResolver:
    def __init__(self, provider: LLMProvider | None) -> None:
        self.provider = provider
        self.chain = None
        if provider is not None:
            from langchain_core.runnables import RunnableLambda

            from app.ai.prompts.intent import INTENT_PROMPT

            self.chain = INTENT_PROMPT | RunnableLambda(self._predict)

    async def resolve(self, message: str) -> IntentQuery:
        if suspicious_instruction(message):
            return IntentQuery(intent=Intent.UNSUPPORTED_REQUEST)
        try:
            fallback = infer_intent(message)
        except ArithmeticError:
            return IntentQuery(intent=Intent.CLARIFICATION)
        if self.chain is None:
            return fallback
        from langsmith import tracing_context

        try:
            with tracing_context(enabled=False):
                result = await self.chain.ainvoke(
                    {"message": message, "categories": ", ".join(slug for slug, _ in _CATEGORIES)}
                )
            filters = result.filters.model_dump(exclude_none=True, exclude_defaults=True)
            explicit = fallback.filters.model_dump(exclude_none=True, exclude_defaults=True)
            if "spec" in explicit:
                keys = {item.key for item in fallback.filters.specification_filters}
                filters["spec"] = [
                    raw for raw in result.filters.spec if raw.split(":", 1)[0] not in keys
                ] + explicit["spec"]
            filters.update({key: value for key, value in explicit.items() if key != "spec"})
            return IntentQuery(
                intent=fallback.intent if fallback.more_ram else result.intent,
                query=result.query or fallback.query,
                filters=ProductFilters.model_validate(filters),
                use_case=result.use_case or fallback.use_case,
                alternative=fallback.alternative or result.alternative,
                more_ram=fallback.more_ram or result.more_ram,
            )
        except (LLMError, ValidationError):
            return fallback

    async def _predict(self, prompt: ChatPromptValue) -> IntentQuery:
        assert self.provider is not None
        messages = [
            ChatMessage("user" if message.type == "human" else "system", message.content)
            for message in prompt.to_messages()
        ]
        raw = await self.provider.generate(messages, schema=IntentQuery.model_json_schema())
        return IntentQuery.model_validate_json(raw)
