from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.modules.catalog.schemas import ProductFilters, ProductRead

type SearchStrategy = Literal["keyword", "semantic", "hybrid"]


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=512)]
    filters: ProductFilters = Field(
        default_factory=ProductFilters, description="Обязательные фильтры."
    )
    top_k: int = Field(default=10, ge=1, le=50, description="Максимальный размер выдачи.")


class RankedProduct(BaseModel):
    product: ProductRead
    score: float = Field(description="Релевантность внутри применённой стратегии.")


class SearchResponse(BaseModel):
    strategy: SearchStrategy
    applied_strategy: SearchStrategy
    items: list[RankedProduct]
