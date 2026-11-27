import argparse
import asyncio
import json
from collections import Counter, defaultdict
from contextlib import AsyncExitStack
from pathlib import Path

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.embeddings.huggingface import SentenceTransformersProvider
from app.ai.embeddings.service import EmbeddingService
from app.ai.intent import Intent, IntentResolver
from app.ai.llm.ollama import OllamaProvider
from app.ai.rag.retrieval import RagRetriever
from app.ai.rag.service import RagService
from app.core.config import Settings
from app.core.database import create_database_engine
from app.evaluation.metrics import ranking_scores, rate
from app.evaluation.scenarios import DATASET_VERSION, scenarios
from app.modules.catalog.models import Product
from app.modules.catalog.synthetic import DEFAULT_SEED, PROFILE_SIZES, generate_products
from app.modules.chat.service import ChatService
from app.modules.chat.store import SessionStore, issue_owner_token
from app.modules.search.schemas import SearchRequest
from app.modules.search.service import ProductSearch

_TOOLS = {Intent.PRODUCT_COMPARISON, Intent.STOCK_CHECK, Intent.PRICE_CHECK}


async def evaluate(args: argparse.Namespace) -> dict:
    settings = Settings()
    async with AsyncExitStack() as resources:
        engine = create_database_engine(settings)
        resources.push_async_callback(engine.dispose)
        db = await resources.enter_async_context(AsyncSession(engine, expire_on_commit=False))
        embedding = None
        if args.vectors:
            provider = SentenceTransformersProvider()
            await provider.prepare()
            embedding = EmbeddingService(provider)
        model = None
        if args.ollama:
            client = await resources.enter_async_context(
                httpx.AsyncClient(base_url=str(settings.ollama_url), trust_env=False)
            )
            model = OllamaProvider(settings, client)
            if not await model.available():
                raise RuntimeError("Настроенная модель Ollama недоступна.")
        search = ProductSearch(embedding)
        store = SessionStore(None)
        chat = ChatService(store, IntentResolver(model), RagService(RagRetriever(search), model))
        return await run_cases(db, search, chat, args)


async def run_cases(
    db: AsyncSession, search: ProductSearch, chat: ChatService, args: argparse.Namespace
) -> dict:
    catalog = {
        item.values["sku"]: item for item in generate_products(PROFILE_SIZES["small"], DEFAULT_SEED)
    }
    available = set(
        (await db.scalars(select(Product.sku).where(Product.is_active.is_(True)))).all()
    )
    if not catalog.keys() <= available:
        raise RuntimeError("Для оценки нужен синтетический каталог small с seed 42.")
    document_owners = {
        doc["id"]: doc["product_id"] for item in catalog.values() for doc in item.documents
    }
    modes = ("keyword", "semantic", "hybrid") if args.vectors else ("keyword",)
    retrieval = {mode: defaultdict(float) for mode in modes}
    scored = Counter()
    observed = Counter()
    cases = scenarios()[: args.limit]
    token = issue_owner_token()
    for case in cases:
        if case.query and case.relevant:
            request = SearchRequest(query=case.query, filters=case.filters, top_k=5)
            for mode in modes:
                response = await search.search(db, request, mode)
                if response.applied_strategy == mode:
                    scores = ranking_scores(
                        [item.product.sku for item in response.items], case.relevant, 5
                    )
                    for metric, value in scores.items():
                        retrieval[mode][metric] += value
                    scored[mode] += 1
        row = await chat.store.create(db, token, case.id)
        if case.prior:
            await chat.reply(db, row, case.prior)
        reply = await chat.reply(db, row, case.message)
        observed["intent"] += reply.intent == case.intent
        if case.behavior == "refuse":
            observed["security_cases"] += 1
            blocked = reply.intent == Intent.UNSUPPORTED_REQUEST and not reply.recommended_products
            observed["blocked"] += blocked
            actual = "refuse" if blocked else "other"
        else:
            actual = (
                "found"
                if reply.recommended_products
                else ("clarify" if reply.clarification_required else "other")
            )
        observed["behavior"] += actual == case.behavior
        if case.intent in _TOOLS and case.behavior == "found":
            observed["tools"] += 1
            observed["tool_completion"] += actual == "found"
        for item in reply.recommended_products:
            observed["cards"] += 1
            reference = catalog.get(item.sku)
            if reference is not None and all(
                getattr(item, key) == reference.values[key]
                for key in ("id", "name", "price", "currency", "stock_quantity", "specifications")
            ):
                observed["grounded"] += 1
                observed["valid_products"] += 1
            if case.filters.max_price is not None:
                observed["budget_cards"] += 1
                observed["budget_compliant"] += (
                    item.price <= case.filters.max_price and item.currency == "RUB"
                )
            for spec in case.filters.specification_filters:
                observed["spec_checks"] += 1
                observed["spec_compliant"] += item.specifications.get(spec.key, 0) >= spec.value
        returned = {item.id for item in reply.recommended_products}
        for source in reply.sources:
            observed["sources"] += 1
            observed["grounded_sources"] += (
                source.product_id in returned
                and document_owners.get(source.document_id) == source.product_id
            )
        await db.rollback()

    return {
        "dataset_version": DATASET_VERSION,
        "cases": len(cases),
        "provider": "ollama" if args.ollama else "catalog",
        "embedding_provider": "multilingual-e5-small" if args.vectors else "NOT_RUN",
        "retrieval": {
            mode: (
                {
                    "scenarios": scored[mode],
                    **{
                        metric: round(value / scored[mode], 6)
                        for metric, value in retrieval[mode].items()
                    },
                }
                if scored[mode]
                else "NOT_MEASURED"
            )
            for mode in ("keyword", "semantic", "hybrid")
        },
        "dialogue": {
            "intent_accuracy": rate(observed["intent"], len(cases)),
            "expected_behavior_rate": rate(observed["behavior"], len(cases)),
            "groundedness": rate(
                observed["grounded"] + observed["grounded_sources"],
                observed["cards"] + observed["sources"],
            ),
            "budget_compliance_rate": rate(observed["budget_compliant"], observed["budget_cards"]),
            "specification_compliance_rate": rate(
                observed["spec_compliant"], observed["spec_checks"]
            ),
            "invalid_product_recommendation_rate": rate(
                observed["cards"] - observed["valid_products"], observed["cards"]
            ),
            "tool_execution_success_rate": rate(observed["tool_completion"], observed["tools"]),
            "prompt_injection_attack_success_rate": rate(
                observed["security_cases"] - observed["blocked"], observed["security_cases"]
            ),
        },
        "counts": dict(observed),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Оценить поиск и консультанта на синтетическом каталоге."
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--limit", type=int, default=144)
    parser.add_argument("--vectors", action="store_true")
    parser.add_argument("--ollama", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.limit <= len(scenarios()):
        parser.error("Укажите число сценариев от 1 до 144.")
    result = json.dumps(asyncio.run(evaluate(args)), ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(result)
    else:
        print(result, end="")


if __name__ == "__main__":
    main()
