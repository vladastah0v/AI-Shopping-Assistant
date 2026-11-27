import os

import httpx
import pytest

base_url = os.environ.get("SHOPPING_TEST_BASE_URL")
pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        not base_url, reason="SHOPPING_TEST_BASE_URL is required for live API tests"
    ),
]


async def test_live_api_reports_real_dependency_status() -> None:
    async with httpx.AsyncClient(base_url=base_url, timeout=5) as client:
        live = await client.get("/health/live")
        ready = await client.get("/health/ready")
        schema = await client.get("/openapi.json")
        catalog = await client.get("/api/v1/products?limit=1")

    assert live.status_code == 200
    assert live.json() == {"status": "ok"}
    assert ready.status_code == 200
    assert ready.json() == {"status": "ready", "postgres": True, "redis": True}
    assert schema.status_code == 200
    assert "503" in schema.json()["paths"]["/health/ready"]["get"]["responses"]
    assert catalog.status_code == 200
    assert catalog.json()["limit"] == 1
