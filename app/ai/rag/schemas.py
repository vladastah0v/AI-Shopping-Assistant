from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.ai.intent import Intent
from app.modules.catalog.models import DocumentType
from app.modules.catalog.schemas import ProductRead


class SourceReference(BaseModel):
    document_id: UUID
    product_id: UUID
    document_type: DocumentType
    title: str
    source: str
    chunk_id: UUID | None = None


class Evidence(BaseModel):
    reference: SourceReference
    excerpt: str


class AnswerPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_ids: list[UUID] = Field(max_length=5)
    document_ids: list[UUID] = Field(default_factory=list, max_length=8)
    emphasis: Literal["fit", "price", "stock", "comparison"] = "fit"


class AnswerMetadata(BaseModel):
    model: str | None = None
    retrieval_duration_ms: float = 0
    generation_duration_ms: float = 0
    mode: Literal["model", "catalog"] = "catalog"


class RagAnswer(BaseModel):
    answer: str
    intent: Intent
    recommended_products: list[ProductRead] = Field(default_factory=list)
    sources: list[SourceReference] = Field(default_factory=list)
    clarification_required: bool = False
    metadata: AnswerMetadata = Field(default_factory=AnswerMetadata)
