from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ChatSession(Base):
    __tablename__ = "chat_sessions"
    __table_args__ = (
        CheckConstraint("owner_token_hash ~ '^[0-9a-f]{64}$'", name="owner_hash_format"),
        CheckConstraint("revision >= 0", name="revision_non_negative"),
        CheckConstraint("jsonb_typeof(state) = 'object'", name="state_object"),
        Index("ix_chat_sessions_owner_updated", "owner_token_hash", "updated_at"),
        Index("ix_chat_sessions_expires_at", "expires_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, server_default=func.gen_random_uuid())
    owner_token_hash: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(160))
    state: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"), deferred=True)
    revision: Mapped[int] = mapped_column(server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ChatMessageRecord(Base):
    __tablename__ = "chat_messages"
    __table_args__ = (
        CheckConstraint("role IN ('user', 'assistant', 'tool')", name="role_allowed"),
        CheckConstraint("position >= 1", name="position_positive"),
        CheckConstraint("char_length(content) BETWEEN 1 AND 16000", name="content_length"),
        UniqueConstraint("session_id", "position", name="uq_chat_messages_session_position"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, server_default=func.gen_random_uuid())
    session_id: Mapped[UUID] = mapped_column(ForeignKey("chat_sessions.id", ondelete="CASCADE"))
    position: Mapped[int]
    role: Mapped[str] = mapped_column(String(10))
    content: Mapped[str] = mapped_column(Text)
    model_name: Mapped[str | None] = mapped_column(String(160))
    details: Mapped[dict] = mapped_column("metadata", JSONB, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RecommendationHistory(Base):
    __tablename__ = "recommendation_history"
    __table_args__ = (
        UniqueConstraint(
            "message_id", "product_id", name="uq_recommendation_history_message_product"
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, server_default=func.gen_random_uuid())
    session_id: Mapped[UUID] = mapped_column(
        ForeignKey("chat_sessions.id", ondelete="CASCADE"), index=True
    )
    message_id: Mapped[UUID] = mapped_column(ForeignKey("chat_messages.id", ondelete="CASCADE"))
    product_id: Mapped[UUID] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), index=True
    )
    recommendation_reason: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Feedback(Base):
    __tablename__ = "feedback"
    __table_args__ = (
        CheckConstraint("rating BETWEEN 1 AND 5", name="rating_range"),
        UniqueConstraint("message_id", name="uq_feedback_message_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, server_default=func.gen_random_uuid())
    session_id: Mapped[UUID] = mapped_column(
        ForeignKey("chat_sessions.id", ondelete="CASCADE"), index=True
    )
    message_id: Mapped[UUID] = mapped_column(ForeignKey("chat_messages.id", ondelete="CASCADE"))
    rating: Mapped[int]
    comment: Mapped[str | None] = mapped_column(String(2000))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class LLMRequestRecord(Base):
    __tablename__ = "llm_requests"
    __table_args__ = (
        CheckConstraint("status IN ('model', 'catalog')", name="status_allowed"),
        CheckConstraint(
            "retrieval_duration_ms >= 0 AND generation_duration_ms >= 0 AND total_duration_ms >= 0",
            name="non_negative_durations",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, server_default=func.gen_random_uuid())
    session_id: Mapped[UUID] = mapped_column(
        ForeignKey("chat_sessions.id", ondelete="CASCADE"), index=True
    )
    model_name: Mapped[str | None] = mapped_column(String(160))
    input_tokens: Mapped[int | None]
    output_tokens: Mapped[int | None]
    retrieval_duration_ms: Mapped[float]
    generation_duration_ms: Mapped[float]
    total_duration_ms: Mapped[float]
    status: Mapped[str] = mapped_column(String(10))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
