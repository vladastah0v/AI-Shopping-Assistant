import json
import logging

import httpx
import pytest

from app.core.observability import JsonFormatter
from app.main import create_app


@pytest.mark.asyncio
async def test_metrics_use_template_paths_without_request_input() -> None:
    app = create_app()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        assert (await client.get("/health/live?private=hidden")).status_code == 200
        assert (await client.get("/unknown/path")).status_code == 404
        response = await client.get("/metrics")
    assert response.status_code == 200
    assert (
        'shopping_http_requests_total{method="GET",route="/health/live",status="200"}'
        in response.text
    )
    assert "private" not in response.text
    assert "/unknown/path" not in response.text


def test_formatter_outputs_bounded_metadata() -> None:
    record = logging.LogRecord(
        "app.http", logging.INFO, __file__, 4, "HTTP request completed", (), None
    )
    record.route = "/api/v1/chat/sessions/{id}"
    record.user_content = "уникальный текст"
    output = json.loads(JsonFormatter().format(record))
    assert output["route"] == "/api/v1/chat/sessions/{id}"
    assert "user_content" not in output
