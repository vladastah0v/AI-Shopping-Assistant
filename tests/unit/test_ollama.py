import json

import httpx
import pytest

from app.ai.llm.ollama import OllamaProvider
from app.ai.llm.provider import ChatMessage, LLMInvalidResponse, LLMUnavailable
from app.core.config import Settings

pytestmark = pytest.mark.asyncio
MESSAGES = [ChatMessage("user", "Подбери ноутбук")]


def settings(**overrides):
    return Settings(_env_file=None, postgres_password="test", **overrides)


async def test_ollama_health_generation_retry_and_schema() -> None:
    calls = []

    def handler(request):
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"model": "qwen2.5:1.5b"}]})
        calls.append(json.loads(request.content))
        if len(calls) == 1:
            return httpx.Response(503)
        return httpx.Response(200, json={"done": True, "message": {"content": "{}"}})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://ollama"
    ) as http:
        provider = OllamaProvider(settings(), http)
        assert await provider.available()
        assert await provider.generate(MESSAGES, schema={"type": "object"}) == "{}"
        assert len(calls) == 2
        assert calls[0] == calls[1]
        assert calls[0]["format"] == {"type": "object"}
        assert calls[0]["stream"] is False
        assert calls[0]["messages"] == [{"role": "user", "content": "Подбери ноутбук"}]


@pytest.mark.parametrize(
    ("ending", "failure"),
    [
        ('{"done":true,"message":{"content":""}}', None),
        ('{"error":"server failure"}', LLMUnavailable),
        ("malformed", LLMInvalidResponse),
        ("", LLMInvalidResponse),
    ],
)
async def test_ollama_streaming_validates_end_marker(ending, failure) -> None:
    payload = '{"done":false,"message":{"content":"Данные"}}\n' + ending
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, text=payload)),
        base_url="http://ollama",
    ) as http:
        provider = OllamaProvider(settings(), http)
        stream = provider.stream(MESSAGES)
        assert await anext(stream) == "Данные"
        with pytest.raises(failure or StopAsyncIteration):
            await anext(stream)


async def test_ollama_reports_missing_model_without_blocking_catalog_apis() -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(404)),
        base_url="http://ollama",
    ) as http:
        provider = OllamaProvider(settings(), http)
        assert not await provider.available()
        with pytest.raises(LLMUnavailable):
            await provider.generate(MESSAGES)
