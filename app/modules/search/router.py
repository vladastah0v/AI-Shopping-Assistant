from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.router import catalog_session
from app.modules.search.schemas import SearchRequest, SearchResponse
from app.modules.search.service import EmbeddingsUnavailable

router = APIRouter(prefix="/api/v1/search", tags=["Поиск"])


async def search_session(request: Request) -> AsyncIterator[AsyncSession]:
    state = request.app.state
    timeout = state.dependency_timeout_seconds + state.product_search.embedding_timeout
    async with catalog_session(request, timeout=timeout) as session:
        yield session


type SearchSession = Annotated[AsyncSession, Depends(search_session, scope="function")]


@router.post("/keyword", summary="Найти товары по тексту и артикулам")
async def keyword(body: SearchRequest, request: Request, session: SearchSession) -> SearchResponse:
    return await request.app.state.product_search.search(session, body, "keyword")


@router.post(
    "/semantic",
    summary="Найти товары по смыслу",
    responses={503: {"description": "Векторная модель или каталог недоступны."}},
)
async def semantic(body: SearchRequest, request: Request, session: SearchSession) -> SearchResponse:
    try:
        return await request.app.state.product_search.search(session, body, "semantic")
    except EmbeddingsUnavailable as error:
        raise HTTPException(503, str(error)) from error


@router.post("/hybrid", summary="Объединить текстовый и семантический поиск")
async def hybrid(body: SearchRequest, request: Request, session: SearchSession) -> SearchResponse:
    return await request.app.state.product_search.search(session, body, "hybrid")
