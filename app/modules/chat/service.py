import re
from time import perf_counter

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.intent import Intent, IntentResolver
from app.ai.rag.schemas import RagAnswer
from app.ai.rag.service import RagService
from app.modules.catalog.models import Product
from app.modules.chat.memory import LOOKUP_INTENTS, SessionMemory, merge_intent, referenced_products
from app.modules.chat.models import (
    ChatMessageRecord,
    ChatSession,
    Feedback,
    LLMRequestRecord,
    RecommendationHistory,
)
from app.modules.chat.schemas import ChatReply, FeedbackCreate, FeedbackRead
from app.modules.chat.store import SessionStore

_SKU = re.compile(r"\b[a-z0-9]{2,}(?:-[a-z0-9]+)*-\d[a-z0-9-]*\b", re.I)
_CATALOG_INTENTS = LOOKUP_INTENTS | {Intent.PRODUCT_SEARCH, Intent.RECOMMENDATION}


class ChatService:
    def __init__(self, store: SessionStore, resolver: IntentResolver, rag: RagService) -> None:
        self.store = store
        self.resolver = resolver
        self.rag = rag

    async def reply(self, db: AsyncSession, row: ChatSession, content: str) -> ChatReply:
        started = perf_counter()
        state = await self.store.load(db, row)
        request = await self.resolver.resolve(content)
        try:
            request = merge_intent(request, state)
        except ValidationError:
            answer = RagAnswer(
                answer="Уточните совместимые условия подбора.",
                intent=Intent.CLARIFICATION,
                clarification_required=True,
            )
        else:
            ids = referenced_products(content, request, state)
            if skus := _SKU.findall(content):
                found = dict(
                    (
                        await db.execute(
                            select(func.lower(Product.sku), Product.id).where(
                                Product.is_active.is_(True),
                                func.lower(Product.sku).in_([sku.lower() for sku in skus[:5]]),
                            )
                        )
                    ).all()
                )
                if found:
                    ids = list(
                        dict.fromkeys(found[sku.lower()] for sku in skus if sku.lower() in found)
                    )[:5]
            if (
                ids
                and request.alternative is None
                and request.intent
                in {Intent.CLARIFICATION, Intent.PRODUCT_SEARCH, Intent.RECOMMENDATION}
            ):
                request = request.model_copy(update={"intent": Intent.PRODUCT_INFORMATION})
            effective = request
            point_lookup = (
                bool(ids) and request.alternative is None and request.intent in LOOKUP_INTENTS
            )
            if point_lookup and request.intent == Intent.STOCK_CHECK:
                effective = request.model_copy(
                    update={"filters": request.filters.model_copy(update={"in_stock": None})}
                )
            answer = await self.rag.answer(db, effective, product_ids=ids)
            if request.intent in _CATALOG_INTENTS and not point_lookup:
                state = SessionMemory(
                    filters=request.filters,
                    query=request.query,
                    use_case=request.use_case,
                    preference=request.alternative or state.preference,
                    product_ids=state.product_ids,
                )
            if answer.recommended_products:
                state.product_ids = [product.id for product in answer.recommended_products]

        position = row.revision * 2 + 1
        self.store.update(row, state)
        response = ChatMessageRecord(
            session_id=row.id,
            position=position + 1,
            role="assistant",
            content=answer.answer,
            model_name=answer.metadata.model,
            details=answer.model_dump(mode="json", exclude={"answer"}),
        )
        db.add_all(
            [
                ChatMessageRecord(
                    session_id=row.id, position=position, role="user", content=content
                ),
                response,
            ]
        )
        await db.flush()
        db.add_all(
            [
                RecommendationHistory(
                    session_id=row.id,
                    message_id=response.id,
                    product_id=item.product_id,
                    recommendation_reason=item.reason,
                )
                for item in answer.recommendations
            ]
        )
        db.add(
            LLMRequestRecord(
                session_id=row.id,
                model_name=answer.metadata.model,
                retrieval_duration_ms=answer.metadata.retrieval_duration_ms,
                generation_duration_ms=answer.metadata.generation_duration_ms,
                total_duration_ms=(perf_counter() - started) * 1000,
                status=answer.metadata.mode,
            )
        )
        return ChatReply(**answer.model_dump(), session_id=row.id, message_id=response.id)


async def record_feedback(db: AsyncSession, body: FeedbackCreate) -> FeedbackRead | None:
    valid = await db.scalar(
        select(ChatMessageRecord.id).where(
            ChatMessageRecord.id == body.message_id,
            ChatMessageRecord.session_id == body.session_id,
            ChatMessageRecord.role == "assistant",
        )
    )
    if valid is None:
        return None
    statement = insert(Feedback).values(**body.model_dump())
    statement = statement.on_conflict_do_update(
        index_elements=[Feedback.message_id],
        set_={"rating": statement.excluded.rating, "comment": statement.excluded.comment},
    ).returning(Feedback)
    return FeedbackRead.model_validate(await db.scalar(statement))
