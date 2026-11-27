import asyncio
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy.exc import OperationalError

from app import main
from app.core.config import Settings

pytestmark = pytest.mark.asyncio


@pytest.fixture
def service_clients(monkeypatch: pytest.MonkeyPatch) -> tuple[MagicMock, MagicMock]:
    engine = MagicMock(dispose=AsyncMock())
    engine.connect.return_value.__aenter__.return_value.execute = AsyncMock()
    redis = MagicMock(ping=AsyncMock(return_value=True), aclose=AsyncMock())
    monkeypatch.setattr(main, "create_database_engine", lambda _: engine)
    monkeypatch.setattr(main, "create_redis_client", lambda _: redis)
    return engine, redis


@pytest.fixture
def application(service_clients: tuple[MagicMock, MagicMock]) -> FastAPI:
    settings = Settings(_env_file=None, postgres_password="test", dependency_timeout_seconds=0.05)
    return main.create_app(settings)


@pytest_asyncio.fixture
async def client(application: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=application)
    async with (
        application.router.lifespan_context(application),
        httpx.AsyncClient(transport=transport, base_url="http://test") as client,
    ):
        yield client


async def test_liveness_only_checks_process(
    client: httpx.AsyncClient, service_clients: tuple[MagicMock, MagicMock]
) -> None:
    engine, redis = service_clients

    response = await client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    engine.connect.assert_not_called()
    redis.ping.assert_not_awaited()


async def test_lifespan_closes_service_clients(
    application: FastAPI, service_clients: tuple[MagicMock, MagicMock]
) -> None:
    engine, redis = service_clients

    async with application.router.lifespan_context(application):
        assert application.state.database_engine is engine
        assert application.state.redis_client is redis

    redis.aclose.assert_awaited_once()
    engine.dispose.assert_awaited_once()


@pytest.mark.parametrize(
    "postgres_ready,redis_ready", [(True, True), (False, True), (True, False), (False, False)]
)
async def test_readiness_reports_each_dependency(
    client: httpx.AsyncClient,
    service_clients: tuple[MagicMock, MagicMock],
    postgres_ready: bool,
    redis_ready: bool,
) -> None:
    engine, redis = service_clients
    if not postgres_ready:
        execute = engine.connect.return_value.__aenter__.return_value.execute
        execute.side_effect = OperationalError("SELECT", None, RuntimeError("unavailable"))
    if not redis_ready:
        redis.ping.side_effect = RedisConnectionError("unavailable")

    response = await client.get("/health/ready")

    ready = postgres_ready and redis_ready
    assert response.status_code == (200 if ready else 503)
    assert response.json() == {
        "status": "ready" if ready else "not_ready",
        "postgres": postgres_ready,
        "redis": redis_ready,
    }


async def test_readiness_times_out_slow_dependency(
    client: httpx.AsyncClient, service_clients: tuple[MagicMock, MagicMock]
) -> None:
    _, redis = service_clients

    async def slow_ping() -> None:
        await asyncio.sleep(10)

    redis.ping.side_effect = slow_ping

    response = await client.get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {"status": "not_ready", "postgres": True, "redis": False}


async def test_optional_ai_status_does_not_affect_readiness(client: httpx.AsyncClient) -> None:
    response = await client.get("/health/ai")
    assert response.status_code == 200
    assert response.json() == {"status": "disabled"}
    assert (await client.get("/health/ready")).status_code == 200
