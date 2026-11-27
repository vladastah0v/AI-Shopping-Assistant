from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, StringConstraints

from app.ai.rag.schemas import RagAnswer

type Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)]
type MessageText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)
]


class SessionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: Title = "Подбор техники"


class SessionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    created_at: datetime
    updated_at: datetime
    expires_at: datetime


class SessionCreated(SessionRead):
    access_token: str = Field(description="Секретный токен владельца сессии.")


class MessageCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: MessageText


class MessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    position: int
    role: Literal["user", "assistant", "tool"]
    content: str
    created_at: datetime
    model_name: str | None
    metadata: dict[str, JsonValue] = Field(validation_alias="details")


class ChatReply(RagAnswer):
    session_id: UUID
    message_id: UUID


class FeedbackCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: UUID
    message_id: UUID
    rating: int = Field(ge=1, le=5)
    comment: MessageText | None = None


class FeedbackRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    session_id: UUID
    message_id: UUID
    rating: int
    comment: str | None
    created_at: datetime
