from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.ai.embeddings.huggingface import SentenceTransformersProvider
from app.ai.embeddings.service import EmbeddingService
from app.ai.intent import IntentResolver
from app.ai.llm.observed import ObservedLLM
from app.ai.llm.ollama import OllamaProvider
from app.ai.llm.provider import LLMProvider
from app.ai.rag.retrieval import RagRetriever
from app.ai.rag.service import RagService
from app.core.cache import RedisCache
from app.core.config import Settings
from app.core.database import create_database_engine
from app.core.http import RequestLimitMiddleware
from app.core.observability import MetricsMiddleware, configure_logging, metrics_endpoint
from app.core.redis import create_redis_client
from app.core.traffic import TrafficLimiter, TrafficMiddleware
from app.health import router as health_router
from app.modules.catalog.router import router as catalog_router
from app.modules.chat.router import router as chat_router
from app.modules.chat.service import ChatService
from app.modules.chat.store import SessionStore
from app.modules.search.router import router as search_router
from app.modules.search.service import ProductSearch


def create_app(
    settings: Settings | None = None,
    *,
    embeddings: EmbeddingService | None = None,
    llm: LLMProvider | None = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        configure_logging()
        config = settings if settings is not None else Settings()
        async with AsyncExitStack() as resources:
            engine = create_database_engine(config)
            resources.push_async_callback(engine.dispose)
            redis_client = create_redis_client(config)
            resources.push_async_callback(redis_client.aclose)

            application.state.database_engine = engine
            application.state.redis_client = redis_client
            application.state.dependency_timeout_seconds = config.dependency_timeout_seconds
            active_embeddings = embeddings
            if active_embeddings is None and config.semantic_search_enabled:
                active_embeddings = EmbeddingService(SentenceTransformersProvider())
            application.state.product_search = ProductSearch(
                active_embeddings,
                embedding_timeout=config.embedding_timeout_seconds,
                cache=RedisCache(redis_client) if config.cache_enabled else None,
                search_ttl=config.search_cache_ttl_seconds,
                vector_ttl=config.embedding_cache_ttl_seconds,
            )
            active_llm = llm
            if active_llm is None and config.ollama_enabled:
                ollama_http = await resources.enter_async_context(
                    httpx.AsyncClient(
                        base_url=str(config.ollama_url),
                        trust_env=False,
                        timeout=httpx.Timeout(
                            config.ollama_generation_timeout_seconds,
                            connect=config.ollama_connection_timeout_seconds,
                        ),
                    )
                )
                active_llm = OllamaProvider(config, ollama_http)
            if active_llm is not None:
                active_llm = ObservedLLM(active_llm)
            application.state.llm = active_llm
            application.state.chat = ChatService(
                SessionStore(
                    redis_client,
                    ttl_seconds=config.chat_session_ttl_seconds,
                    history_limit=config.chat_history_limit,
                ),
                IntentResolver(active_llm),
                RagService(RagRetriever(application.state.product_search), active_llm),
            )
            application.state.chat_timeout = (
                config.dependency_timeout_seconds
                + 2 * config.ollama_generation_timeout_seconds
                + 2 * config.embedding_timeout_seconds
            )
            application.state.traffic = TrafficLimiter(
                redis_client,
                per_minute=config.api_requests_per_minute,
                concurrency=config.active_ai_requests,
                lease_seconds=int(application.state.chat_timeout) + 5,
            )
            yield

    application = FastAPI(
        title="AI Shopping Assistant",
        description="API AI-консультанта интернет-магазина электроники и бытовой техники.",
        version="0.1.0",
        lifespan=lifespan,
    )
    application.add_middleware(TrafficMiddleware)
    application.add_middleware(RequestLimitMiddleware)
    application.add_middleware(MetricsMiddleware)
    application.add_api_route(
        "/metrics",
        metrics_endpoint,
        summary="Получить метрики Prometheus",
        tags=["Состояние сервиса"],
    )

    @application.exception_handler(RequestValidationError)
    async def invalid_input(_: Request, error: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "detail": [
                    {key: item[key] for key in ("loc", "type", "msg")} for item in error.errors()
                ]
            },
        )

    application.include_router(health_router)
    application.include_router(catalog_router)
    application.include_router(search_router)
    application.include_router(chat_router)
    return application


app = create_app()
