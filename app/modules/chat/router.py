import json
from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.router import catalog_session
from app.modules.chat.models import ChatSession, LLMRequestRecord
from app.modules.chat.schemas import (
    ChatReply,
    FeedbackCreate,
    FeedbackRead,
    MessageCreate,
    MessageRead,
    SessionCreate,
    SessionCreated,
    SessionRead,
)
from app.modules.chat.service import record_feedback
from app.modules.chat.store import issue_owner_token, owner_hash

router = APIRouter(prefix="/api/v1/chat", tags=["Консультант"])
_bearer = HTTPBearer(
    auto_error=False, description="Секрет владельца, выданный при создании сессии."
)


def _credentials(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> str | None:
    if credentials is None:
        return None
    token = credentials.credentials
    try:
        owner_hash(token)
    except ValueError as error:
        raise HTTPException(
            401, "Некорректный секрет сессии.", headers={"WWW-Authenticate": "Bearer"}
        ) from error
    return token


def _authenticated(token: Annotated[str | None, Depends(_credentials)]) -> str:
    if token is None:
        raise HTTPException(401, "Укажите секрет сессии.", headers={"WWW-Authenticate": "Bearer"})
    return token


async def chat_db(request: Request) -> AsyncIterator[AsyncSession]:
    async with catalog_session(request, timeout=request.app.state.dependency_timeout_seconds) as db:
        yield db


type ChatDB = Annotated[AsyncSession, Depends(chat_db, scope="function")]
type OwnerToken = Annotated[str, Depends(_authenticated)]
type OptionalOwner = Annotated[str | None, Depends(_credentials)]


async def _eligible(
    db: AsyncSession, request: Request, token: str, session_id: UUID, *, lock: bool = False
) -> ChatSession:
    row = await request.app.state.chat.store.get(db, token, session_id, lock=lock)
    if row is None:
        raise HTTPException(404, "Сессия не найдена.")
    return row


@router.post("/sessions", summary="Создать сессию консультанта", status_code=201)
async def create_session(
    body: SessionCreate, request: Request, db: ChatDB, token: OptionalOwner
) -> SessionCreated:
    token = token or issue_owner_token()
    row = await request.app.state.chat.store.create(db, token, body.title)
    result = SessionCreated(**SessionRead.model_validate(row).model_dump(), access_token=token)
    await db.commit()
    return result


@router.get("/sessions", summary="Перечислить свои сессии")
async def list_sessions(
    request: Request,
    db: ChatDB,
    token: OwnerToken,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0, le=2**31 - 1)] = 0,
) -> list[SessionRead]:
    rows = await request.app.state.chat.store.list_sessions(db, token, limit=limit, offset=offset)
    return [SessionRead.model_validate(row) for row in rows]


@router.get("/sessions/{id}", summary="Получить свою сессию")
async def get_session(id: UUID, request: Request, db: ChatDB, token: OwnerToken) -> SessionRead:
    return SessionRead.model_validate(await _eligible(db, request, token, id))


@router.delete("/sessions/{id}", summary="Удалить сессию и историю", status_code=204)
async def delete_session(id: UUID, request: Request, db: ChatDB, token: OwnerToken) -> Response:
    await db.delete(await _eligible(db, request, token, id, lock=True))
    await db.commit()
    return Response(status_code=204)


@router.get("/sessions/{id}/messages", summary="Прочитать последние сообщения")
async def history(
    id: UUID,
    request: Request,
    db: ChatDB,
    token: OwnerToken,
    before: Annotated[int | None, Query(ge=1)] = None,
    limit: Annotated[int | None, Query(ge=1, le=50)] = None,
) -> list[MessageRead]:
    row = await _eligible(db, request, token, id)
    messages = await request.app.state.chat.store.history(db, row, before=before, limit=limit)
    return [MessageRead.model_validate(message) for message in messages]


@router.delete("/sessions/{id}/messages", summary="Очистить сообщения и память", status_code=204)
async def clear_history(id: UUID, request: Request, db: ChatDB, token: OwnerToken) -> Response:
    row = await _eligible(db, request, token, id, lock=True)
    await request.app.state.chat.store.clear(db, row)
    await db.execute(delete(LLMRequestRecord).where(LLMRequestRecord.session_id == row.id))
    await db.commit()
    return Response(status_code=204)


async def _reply(request: Request, token: str, id: UUID, body: MessageCreate) -> ChatReply:
    async with catalog_session(request, timeout=request.app.state.chat_timeout) as db:
        row = await _eligible(db, request, token, id, lock=True)
        result = await request.app.state.chat.reply(db, row, body.content)
        await db.commit()
        return result


@router.post("/sessions/{id}/messages", summary="Отправить сообщение консультанту")
async def reply(id: UUID, body: MessageCreate, request: Request, token: OwnerToken) -> ChatReply:
    return await _reply(request, token, id, body)


@router.post(
    "/sessions/{id}/stream",
    summary="Получить проверенный ответ потоком SSE",
    response_class=StreamingResponse,
    responses={200: {"content": {"text/event-stream": {}}}},
)
async def stream(
    id: UUID, body: MessageCreate, request: Request, db: ChatDB, token: OwnerToken
) -> StreamingResponse:
    await _eligible(db, request, token, id)

    async def events() -> AsyncIterator[str]:
        yield 'event: accepted\ndata: {"status":"accepted"}\n\n'
        try:
            result = await _reply(request, token, id, body)
        except HTTPException as error:
            payload = json.dumps({"detail": error.detail}, ensure_ascii=False)
            yield f"event: error\ndata: {payload}\n\n"
            return
        yield f"event: result\ndata: {result.model_dump_json()}\n\n"

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


@router.post("/feedback", summary="Оценить ответ консультанта")
async def feedback(
    body: FeedbackCreate, request: Request, db: ChatDB, token: OwnerToken
) -> FeedbackRead:
    await _eligible(db, request, token, body.session_id, lock=True)
    result = await record_feedback(db, body)
    if result is None:
        raise HTTPException(404, "Ответ консультанта не найден.")
    await db.commit()
    return result
