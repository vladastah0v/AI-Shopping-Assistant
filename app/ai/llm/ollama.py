import asyncio
import json
from collections.abc import AsyncIterator, Sequence
from dataclasses import asdict

import httpx
from pydantic import BaseModel, StrictBool

from app.ai.llm.provider import ChatMessage, LLMInvalidResponse, LLMUnavailable
from app.core.config import Settings


class _Message(BaseModel):
    content: str


class _Chunk(BaseModel):
    message: _Message
    done: StrictBool
    done_reason: str | None = None


class _Model(BaseModel):
    model: str


class _Models(BaseModel):
    models: list[_Model]


_TRANSIENT = (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout)
_RETRY_STATUS = {429, 502, 503, 504}


class OllamaProvider:
    def __init__(self, settings: Settings, client: httpx.AsyncClient) -> None:
        self.model = settings.ollama_model
        self._client = client
        self._timeout = settings.ollama_generation_timeout_seconds
        self._health_timeout = settings.ollama_connection_timeout_seconds
        self._retries = settings.ollama_retries
        self._slots = asyncio.Semaphore(settings.ollama_concurrency)
        self._options = {
            "temperature": settings.ollama_temperature,
            "num_predict": settings.ollama_max_tokens,
            "num_ctx": settings.ollama_context_tokens,
        }

    async def available(self) -> bool:
        try:
            async with asyncio.timeout(self._health_timeout):
                response = await self._client.get("/api/tags")
                response.raise_for_status()
                models = _Models.model_validate_json(response.content)
                model = self.model if ":" in self.model else f"{self.model}:latest"
                return any(item.model == model for item in models.models)
        except (httpx.HTTPError, TimeoutError, ValueError):
            return False

    async def generate(self, messages: Sequence[ChatMessage], *, schema: dict | None = None) -> str:
        payload = self._payload(messages, schema, stream=False)
        try:
            async with asyncio.timeout(self._timeout), self._slots:
                for attempt in range(self._retries + 1):
                    try:
                        response = await self._client.post("/api/chat", json=payload)
                        if response.status_code in _RETRY_STATUS and attempt < self._retries:
                            await asyncio.sleep(0.1 * (attempt + 1))
                            continue
                        response.raise_for_status()
                        chunk = _Chunk.model_validate_json(response.content)
                        if chunk.done and chunk.done_reason != "length" and chunk.message.content:
                            return chunk.message.content
                        raise LLMInvalidResponse("Модель не завершила ответ.")
                    except _TRANSIENT:
                        if attempt == self._retries:
                            raise
                        await asyncio.sleep(0.1 * (attempt + 1))
        except (httpx.HTTPError, TimeoutError) as error:
            raise LLMUnavailable("Языковая модель временно недоступна.") from error
        except ValueError as error:
            raise LLMInvalidResponse("Ответ языковой модели не распознан.") from error
        raise LLMUnavailable("Языковая модель временно недоступна.")

    async def stream(
        self, messages: Sequence[ChatMessage], *, schema: dict | None = None
    ) -> AsyncIterator[str]:
        payload = self._payload(messages, schema, stream=True)
        try:
            async with (
                asyncio.timeout(self._timeout),
                self._slots,
                self._client.stream("POST", "/api/chat", json=payload) as response,
            ):
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line:
                        continue
                    record = json.loads(line)
                    if isinstance(record, dict) and "error" in record:
                        raise LLMUnavailable("Языковая модель прервала генерацию.")
                    chunk = _Chunk.model_validate(record)
                    if chunk.done_reason == "length":
                        raise LLMInvalidResponse("Модель достигла ограничения длины ответа.")
                    if chunk.message.content:
                        yield chunk.message.content
                    if chunk.done:
                        return
        except (httpx.HTTPError, TimeoutError) as error:
            raise LLMUnavailable("Языковая модель временно недоступна.") from error
        except ValueError as error:
            raise LLMInvalidResponse("Ответ языковой модели не распознан.") from error
        raise LLMInvalidResponse("Модель не завершила поток ответа.")

    def _payload(
        self, messages: Sequence[ChatMessage], schema: dict | None, *, stream: bool
    ) -> dict:
        request = {
            "model": self.model,
            "messages": [asdict(message) for message in messages],
            "options": self._options,
            "stream": stream,
        }
        if schema is not None:
            request["format"] = schema
        return request
