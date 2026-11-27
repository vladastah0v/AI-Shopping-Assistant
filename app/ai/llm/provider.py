from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol


@dataclass(frozen=True, slots=True)
class ChatMessage:
    role: Literal["system", "user", "assistant"]
    content: str


class LLMError(Exception):
    pass


class LLMUnavailable(LLMError):
    pass


class LLMInvalidResponse(LLMError):
    pass


class LLMProvider(Protocol):
    model: str

    async def available(self) -> bool:
        raise NotImplementedError

    async def generate(self, messages: Sequence[ChatMessage], *, schema: dict | None = None) -> str:
        raise NotImplementedError

    def stream(
        self, messages: Sequence[ChatMessage], *, schema: dict | None = None
    ) -> AsyncIterator[str]:
        raise NotImplementedError
