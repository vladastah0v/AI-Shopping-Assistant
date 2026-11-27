import re
import secrets
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import UUID

from pydantic import ValidationError
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.chat.memory import SessionMemory
from app.modules.chat.models import ChatMessageRecord, ChatSession

_TOKEN = re.compile(r"[A-Za-z0-9_-]{43}")


def issue_owner_token() -> str:
    return secrets.token_urlsafe(32)


def owner_hash(token: str) -> str:
    if _TOKEN.fullmatch(token) is None:
        raise ValueError("Некорректный секретный токен.")
    return sha256(token.encode("ascii")).hexdigest()


class SessionStore:
    def __init__(
        self, redis: Redis | None, *, ttl_seconds: int = 86400, history_limit: int = 12
    ) -> None:
        self.redis = redis
        self.ttl = timedelta(seconds=ttl_seconds)
        self.history_limit = history_limit

    async def create(self, db: AsyncSession, token: str, title: str) -> ChatSession:
        now = datetime.now(UTC)
        row = ChatSession(
            owner_token_hash=owner_hash(token),
            title=title,
            expires_at=now + self.ttl,
            created_at=now,
            updated_at=now,
        )
        db.add(row)
        await db.flush()
        return row

    async def get(
        self, db: AsyncSession, token: str, session_id: UUID, *, lock: bool = False
    ) -> ChatSession | None:
        query = select(ChatSession).where(
            ChatSession.id == session_id,
            ChatSession.owner_token_hash == owner_hash(token),
            ChatSession.expires_at > datetime.now(UTC),
        )
        if lock:
            query = query.with_for_update()
        return await db.scalar(query)

    async def list_sessions(
        self, db: AsyncSession, token: str, *, limit: int = 20, offset: int = 0
    ) -> list[ChatSession]:
        query = (
            select(ChatSession)
            .where(
                ChatSession.owner_token_hash == owner_hash(token),
                ChatSession.expires_at > datetime.now(UTC),
            )
            .order_by(ChatSession.updated_at.desc(), ChatSession.id)
            .limit(limit)
            .offset(offset)
        )
        return list(await db.scalars(query))

    async def load(self, db: AsyncSession, row: ChatSession) -> SessionMemory:
        cache_key = f"shopping:chat:state:v1:{row.id}:{row.revision}:{row.updated_at.isoformat()}"
        if self.redis is not None:
            try:
                raw = await self.redis.get(cache_key)
                if raw is not None:
                    return SessionMemory.model_validate_json(raw)
            except (RedisError, ValidationError):
                pass
        await db.refresh(row, attribute_names=["state"])
        result = SessionMemory.model_validate(row.state)
        if self.redis is not None:
            seconds = max(1, int((row.expires_at - datetime.now(UTC)).total_seconds()))
            try:
                await self.redis.set(cache_key, result.model_dump_json(), ex=seconds)
            except RedisError:
                pass
        return result

    async def history(
        self,
        db: AsyncSession,
        row: ChatSession,
        *,
        before: int | None = None,
        limit: int | None = None,
    ) -> list[ChatMessageRecord]:
        query = select(ChatMessageRecord).where(ChatMessageRecord.session_id == row.id)
        if before is not None:
            query = query.where(ChatMessageRecord.position < before)
        records = await db.scalars(
            query.order_by(ChatMessageRecord.position.desc()).limit(limit or self.history_limit)
        )
        return list(reversed(list(records)))

    async def clear(self, db: AsyncSession, row: ChatSession) -> None:
        await db.execute(delete(ChatMessageRecord).where(ChatMessageRecord.session_id == row.id))
        self.update(row, SessionMemory())

    def update(self, row: ChatSession, state: SessionMemory) -> None:
        row.revision += 1
        row.updated_at = datetime.now(UTC)
        row.expires_at = row.updated_at + self.ttl
        row.state = state.model_dump(mode="json")
