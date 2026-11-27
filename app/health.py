import asyncio
from typing import Literal

from fastapi import APIRouter, Request, Response, status
from pydantic import BaseModel

from app.core.database import postgres_is_ready
from app.core.redis import redis_is_ready

router = APIRouter(prefix="/health", tags=["Состояние сервиса"])


class LivenessResponse(BaseModel):
    status: Literal["ok"] = "ok"


class ReadinessResponse(BaseModel):
    status: Literal["ready", "not_ready"]
    postgres: bool
    redis: bool


@router.get("/live", summary="Проверить, что процесс API отвечает")
async def liveness() -> LivenessResponse:
    return LivenessResponse()


@router.get(
    "/ready",
    summary="Проверить готовность PostgreSQL с pgvector и Redis",
    responses={
        503: {
            "model": ReadinessResponse,
            "description": "Одна или несколько зависимостей недоступны",
        }
    },
)
async def readiness(request: Request, response: Response) -> ReadinessResponse:
    state = request.app.state
    postgres_ready, redis_ready = await asyncio.gather(
        postgres_is_ready(state.database_engine, state.dependency_timeout_seconds),
        redis_is_ready(state.redis_client, state.dependency_timeout_seconds),
    )
    if postgres_ready and redis_ready:
        return ReadinessResponse(status="ready", postgres=True, redis=True)

    response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadinessResponse(status="not_ready", postgres=postgres_ready, redis=redis_ready)


class AIHealthResponse(BaseModel):
    status: Literal["ready", "disabled", "unavailable"]


@router.get("/ai", summary="Проверить доступность настроенной модели Ollama")
async def ai_readiness(request: Request) -> AIHealthResponse:
    llm = request.app.state.llm
    if llm is None:
        return AIHealthResponse(status="disabled")
    return AIHealthResponse(status="ready" if await llm.available() else "unavailable")
