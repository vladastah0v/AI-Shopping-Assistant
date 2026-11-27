from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager

import httpx
from fastapi import FastAPI

from app.ai.embeddings.huggingface import SentenceTransformersProvider
from app.ai.embeddings.service import EmbeddingService
from app.ai.llm.ollama import OllamaProvider
from app.ai.llm.provider import LLMProvider
from app.core.config import Settings
from app.core.database import create_database_engine
from app.core.redis import create_redis_client
from app.health import router as health_router
from app.modules.catalog.router import router as catalog_router
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
                active_embeddings, embedding_timeout=config.embedding_timeout_seconds
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
            application.state.llm = active_llm
            yield

    application = FastAPI(
        title="AI Shopping Assistant",
        description="API AI-консультанта интернет-магазина электроники и бытовой техники.",
        version="0.1.0",
        lifespan=lifespan,
    )
    application.include_router(health_router)
    application.include_router(catalog_router)
    application.include_router(search_router)
    return application


app = create_app()
