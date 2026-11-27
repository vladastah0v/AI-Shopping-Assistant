import asyncio
import logging
from decimal import Decimal
from time import perf_counter
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, ValidationError, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.intent import Intent, IntentQuery
from app.core.observability import TOOL_FAILURES, TOOL_SECONDS
from app.modules.catalog.models import Category
from app.modules.catalog.repository import get_products_by_id, list_products
from app.modules.catalog.schemas import CategoryRead, ProductFilters, ProductQuery, ProductRead
from app.modules.search.schemas import SearchRequest
from app.modules.search.service import ProductSearch

logger = logging.getLogger(__name__)

type ToolName = Literal[
    "search_products",
    "get_product_details",
    "compare_products",
    "check_stock",
    "get_product_price",
    "get_product_specifications",
    "find_alternatives",
    "get_category_information",
]


class ToolCall(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: ToolName
    arguments: dict[str, JsonValue]


class SearchArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(default="", max_length=512)
    filters: ProductFilters = Field(default_factory=ProductFilters)
    limit: int = Field(default=5, ge=1, le=20)


class ProductArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_ids: list[UUID] = Field(min_length=1, max_length=5)
    filters: ProductFilters = Field(default_factory=ProductFilters)

    @field_validator("product_ids")
    @classmethod
    def unique_ids(cls, value: list[UUID]) -> list[UUID]:
        if len(value) != len(set(value)):
            raise ValueError("Товары в запросе должны различаться.")
        return value


class AlternativeArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: UUID
    filters: ProductFilters = Field(default_factory=ProductFilters)
    cheaper: bool = False
    more_ram: bool = False
    limit: int = Field(default=5, ge=1, le=20)


class CategoryArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slug: str = Field(max_length=120, pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$")


class ToolResult(BaseModel):
    products: list[ProductRead] = Field(default_factory=list)
    category: CategoryRead | None = None
    specifications: dict[str, list[JsonValue]] = Field(default_factory=dict)


class ToolError(Exception):
    pass


class CatalogTools:
    def __init__(self, search: ProductSearch, *, timeout: float = 12) -> None:
        self.search = search
        self.timeout = timeout

    async def execute(self, session: AsyncSession, calls: list[ToolCall]) -> list[ToolResult]:
        if not 1 <= len(calls) <= 3:
            raise ToolError("За один запрос разрешено от одного до трёх инструментов.")
        results = []
        try:
            async with asyncio.timeout(self.timeout):
                for call in calls:
                    started = perf_counter()
                    try:
                        results.append(await self._dispatch(session, call))
                    except Exception:
                        TOOL_FAILURES.labels(call.name).inc()
                        raise
                    finally:
                        TOOL_SECONDS.labels(call.name).observe(perf_counter() - started)
                        logger.info(
                            "Catalog tool completed",
                            extra={
                                "tool": call.name,
                                "duration_ms": (perf_counter() - started) * 1000,
                            },
                        )
        except ValidationError as error:
            raise ToolError("Аргументы инструмента отклонены.") from error
        except TimeoutError as error:
            raise ToolError("Инструмент каталога не ответил вовремя.") from error
        return results

    async def _dispatch(self, session: AsyncSession, call: ToolCall) -> ToolResult:
        match call.name:
            case "search_products":
                arguments = SearchArguments.model_validate(call.arguments)
                if arguments.query.strip():
                    result = await self.search.search(
                        session,
                        SearchRequest(
                            query=arguments.query, filters=arguments.filters, top_k=arguments.limit
                        ),
                        "hybrid",
                    )
                    return ToolResult(products=[item.product for item in result.items])
                query = ProductQuery(
                    **arguments.filters.model_dump(), limit=arguments.limit, sort="rating_desc"
                )
                return ToolResult(products=await self._list_cards(session, query))
            case "find_alternatives":
                arguments = AlternativeArguments.model_validate(call.arguments)
                return await self._alternatives(session, arguments)
            case "get_category_information":
                arguments = CategoryArguments.model_validate(call.arguments)
                row = await session.scalar(select(Category).where(Category.slug == arguments.slug))
                return ToolResult(category=CategoryRead.model_validate(row) if row else None)
            case (
                "get_product_details"
                | "compare_products"
                | "check_stock"
                | "get_product_price"
                | "get_product_specifications"
            ):
                return await self._product_lookup(session, call)
        raise ToolError("Инструмент недоступен.")

    async def _product_lookup(self, session: AsyncSession, call: ToolCall) -> ToolResult:
        arguments = ProductArguments.model_validate(call.arguments)
        if call.name == "compare_products" and len(arguments.product_ids) < 2:
            raise ToolError("Укажите хотя бы два товара для сравнения.")
        rows = await get_products_by_id(session, arguments.product_ids, filters=arguments.filters)
        products = [
            ProductRead.model_validate(rows[key]) for key in arguments.product_ids if key in rows
        ]
        if call.name == "compare_products" and len(products) != len(arguments.product_ids):
            return ToolResult()
        specs = {}
        if call.name in {"compare_products", "get_product_specifications"}:
            specs = {
                key: [product.specifications.get(key) for product in products]
                for key in sorted({key for product in products for key in product.specifications})
            }
        return ToolResult(products=products, specifications=specs)

    async def _alternatives(
        self, session: AsyncSession, arguments: AlternativeArguments
    ) -> ToolResult:
        source = (await get_products_by_id(session, [arguments.product_id])).get(
            arguments.product_id
        )
        if source is None:
            return ToolResult()
        constraints = arguments.filters.model_dump(exclude_none=True)
        if arguments.cheaper:
            maximum = source.price - Decimal("0.01")
            if arguments.filters.max_price is not None:
                maximum = min(maximum, arguments.filters.max_price)
            if maximum < 0 or maximum < (arguments.filters.min_price or 0):
                return ToolResult()
            if arguments.filters.currency not in (None, source.currency):
                return ToolResult()
            constraints.update(max_price=maximum, currency=source.currency)
        if arguments.more_ram:
            memory = source.specifications.get("ram_gb")
            if type(memory) not in (int, float):
                return ToolResult()
            previous = arguments.filters.spec
            if len(previous) >= 12:
                raise ToolError("Уточните требования к оперативной памяти.")
            constraints["spec"] = [*previous, f"ram_gb:gte:{int(memory) + 1}"]
        constraints.setdefault("category_id", source.category_id)
        constraints.setdefault("in_stock", True)
        query = ProductQuery(**constraints, limit=arguments.limit + 1, sort="price_asc")
        cards = await self._list_cards(session, query)
        return ToolResult(
            products=[item for item in cards if item.id != source.id][: arguments.limit]
        )

    @staticmethod
    async def _list_cards(session: AsyncSession, query: ProductQuery) -> list[ProductRead]:
        return [
            ProductRead.model_validate(row)
            for row in (await list_products(session, query))[: query.limit]
        ]


_LOOKUP_TOOLS: dict[Intent, ToolName] = {
    Intent.PRODUCT_INFORMATION: "get_product_details",
    Intent.PRODUCT_COMPARISON: "compare_products",
    Intent.STOCK_CHECK: "check_stock",
    Intent.PRICE_CHECK: "get_product_price",
}


def route_lookup(request: IntentQuery, product_ids: list[UUID]) -> ToolCall | None:
    name = _LOOKUP_TOOLS.get(request.intent)
    if name is None or not product_ids:
        return None
    arguments = ProductArguments(product_ids=product_ids, filters=request.filters)
    return ToolCall(name=name, arguments=arguments.model_dump(mode="json"))
