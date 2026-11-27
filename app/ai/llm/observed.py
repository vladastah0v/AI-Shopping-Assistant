from collections.abc import AsyncIterator, Iterator, Sequence
from contextlib import aclosing, contextmanager

from app.ai.llm.provider import ChatMessage, LLMInvalidResponse, LLMProvider
from app.core.observability import INVALID_AI, LLM_FAILURES, LLM_REQUESTS, LLM_SECONDS


@contextmanager
def _record(mode: str) -> Iterator[None]:
    status = "cancelled"
    with LLM_SECONDS.labels(mode).time():
        try:
            yield
        except Exception as error:
            status = "failed"
            LLM_FAILURES.labels(mode).inc()
            if isinstance(error, LLMInvalidResponse):
                INVALID_AI.labels("provider").inc()
            raise
        else:
            status = "ok"
        finally:
            LLM_REQUESTS.labels(mode, status).inc()


class ObservedLLM:
    def __init__(self, provider: LLMProvider) -> None:
        self.provider = provider
        self.model = provider.model

    async def available(self) -> bool:
        return await self.provider.available()

    async def generate(self, messages: Sequence[ChatMessage], *, schema: dict | None = None) -> str:
        with _record("complete"):
            return await self.provider.generate(messages, schema=schema)

    async def stream(
        self, messages: Sequence[ChatMessage], *, schema: dict | None = None
    ) -> AsyncIterator[str]:
        with _record("stream"):
            async with aclosing(self.provider.stream(messages, schema=schema)) as chunks:
                async for chunk in chunks:
                    yield chunk
