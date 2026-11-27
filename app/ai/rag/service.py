import json
from time import perf_counter
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.intent import Intent, IntentQuery
from app.ai.llm.provider import ChatMessage, LLMError, LLMProvider
from app.ai.prompts.rag import RAG_PROMPT
from app.ai.rag.retrieval import RagContext, RagRetriever
from app.ai.rag.schemas import AnswerMetadata, AnswerPlan, RagAnswer
from app.ai.tools.catalog import CatalogTools, ToolError, route_lookup
from app.modules.catalog.schemas import ProductRead

_CONTEXT_LIMIT = 8_000
_STATIC_ANSWERS = {
    Intent.GENERAL_CONVERSATION: "Помогу подобрать или сравнить товары. Что вы ищете?",
    Intent.CLARIFICATION: "Уточните категорию товара, название модели или желаемые характеристики.",
    Intent.UNSUPPORTED_REQUEST: "Я могу помочь с поиском, наличием и сравнением товаров каталога.",
}
_HEADINGS = {
    "fit": "По вашему запросу найдены товары.",
    "price": "Актуальные цены в каталоге.",
    "stock": "Остатки по данным каталога.",
    "comparison": "Сравнение выбранных товаров.",
}


def _model_context(request: IntentQuery, context: RagContext) -> tuple[str, set[UUID], set[UUID]]:
    payload = {
        "intent": request.intent,
        "filters": request.filters.model_dump(
            mode="json", exclude_defaults=True, exclude_none=True
        ),
        "products": [],
        "evidence": [],
    }
    used = len(json.dumps(payload, ensure_ascii=False)) + 16
    product_ids = set()
    document_ids = set()
    for product in context.products:
        row = product.model_dump(mode="json", exclude={"description"})
        length = len(json.dumps(row, ensure_ascii=False)) + 2
        if used + length <= _CONTEXT_LIMIT:
            payload["products"].append(row)
            product_ids.add(product.id)
            used += length
    for evidence in context.evidence:
        row = evidence.model_dump(mode="json")
        length = len(json.dumps(row, ensure_ascii=False)) + 2
        if evidence.reference.product_id in product_ids and used + length <= _CONTEXT_LIMIT:
            payload["evidence"].append(row)
            document_ids.add(evidence.reference.document_id)
            used += length
    return json.dumps(payload, ensure_ascii=False), product_ids, document_ids


def validate_plan(plan: AnswerPlan, context: RagContext) -> None:
    products = set(plan.product_ids)
    sources_by_id = {
        item.reference.document_id: item.reference.product_id for item in context.evidence
    }
    if not products or len(products) != len(plan.product_ids):
        raise ValueError("Некорректный список товаров.")
    if not products <= {product.id for product in context.products}:
        raise ValueError("Ответ ссылается на товар за пределами контекста.")
    if len(set(plan.document_ids)) != len(plan.document_ids) or any(
        sources_by_id.get(document) not in products for document in plan.document_ids
    ):
        raise ValueError("Ответ ссылается на документ за пределами выбранных товаров.")


class RagService:
    def __init__(self, retriever: RagRetriever, provider: LLMProvider | None) -> None:
        self.retriever = retriever
        self.provider = provider
        self.tools = CatalogTools(retriever.search)

    async def answer(
        self, session: AsyncSession, request: IntentQuery, *, product_ids: list[UUID] | None = None
    ) -> RagAnswer:
        if request.intent in _STATIC_ANSWERS:
            return RagAnswer(
                answer=_STATIC_ANSWERS[request.intent],
                intent=request.intent,
                clarification_required=request.intent == Intent.CLARIFICATION,
            )
        started = perf_counter()
        lookup = route_lookup(request, product_ids or [])
        if lookup is None:
            context = await self.retriever.retrieve(session, request)
        else:
            try:
                result = (await self.tools.execute(session, [lookup]))[0]
            except ToolError:
                return RagAnswer(
                    answer="Уточните, какие товары нужно проверить.",
                    intent=request.intent,
                    clarification_required=True,
                )
            context = RagContext(
                products=result.products,
                evidence=await self.retriever.retrieve_evidence(session, request, result.products),
            )
        return await self.respond(request, context, (perf_counter() - started) * 1000)

    async def respond(
        self, request: IntentQuery, context: RagContext, retrieval_ms: float = 0
    ) -> RagAnswer:
        metadata = AnswerMetadata(retrieval_duration_ms=retrieval_ms)
        if not context.products:
            return RagAnswer(
                answer="Подходящих товаров не найдено. Уточните модель или измените условия поиска.",
                intent=request.intent,
                clarification_required=True,
                metadata=metadata,
            )
        selected = context.products[:3]
        document_ids = [
            evidence.reference.document_id
            for evidence in context.evidence
            if evidence.reference.product_id in {item.id for item in selected}
        ][:8]
        emphasis = {
            Intent.PRICE_CHECK: "price",
            Intent.STOCK_CHECK: "stock",
            Intent.PRODUCT_COMPARISON: "comparison",
        }.get(request.intent, "fit")
        prompt, product_ids, sent_documents = _model_context(request, context)
        if self.provider is not None and product_ids:
            started = perf_counter()
            try:
                text = await self.provider.generate(
                    [ChatMessage("system", RAG_PROMPT), ChatMessage("user", prompt)],
                    schema=AnswerPlan.model_json_schema(),
                )
                plan = AnswerPlan.model_validate_json(text)
                validate_plan(plan, context)
                if set(plan.product_ids) - product_ids or set(plan.document_ids) - sent_documents:
                    raise ValueError("Ответ ссылается на данные вне отправленного контекста.")
                by_id = {product.id: product for product in context.products}
                selected = [by_id[product_id] for product_id in plan.product_ids]
                document_ids = plan.document_ids
                if emphasis == "fit":
                    emphasis = plan.emphasis
                metadata.model = self.provider.model
                metadata.mode = "model"
            except (LLMError, ValidationError, ValueError):
                pass
            metadata.generation_duration_ms = (perf_counter() - started) * 1000
        sources = {item.reference.document_id: item.reference for item in context.evidence}
        return RagAnswer(
            intent=request.intent,
            answer=self.render(emphasis, selected),
            recommended_products=selected,
            sources=[sources[document_id] for document_id in document_ids],
            metadata=metadata,
        )

    @staticmethod
    def render(emphasis: str, products: list[ProductRead]) -> str:
        lines = [_HEADINGS[emphasis]]
        for index, product in enumerate(products, start=1):
            stock = (
                f"в наличии {product.stock_quantity} шт."
                if product.stock_quantity
                else "нет в наличии"
            )
            lines.append(
                f"{index}. {product.name} — {product.price:.2f} {product.currency}, {stock}"
            )
        return "\n".join(lines)
