import asyncio

from asyncpg import PostgresError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.core.config import Settings


def create_database_engine(settings: Settings) -> AsyncEngine:
    return create_async_engine(
        settings.database_url,
        pool_pre_ping=True,
        connect_args={"timeout": settings.dependency_timeout_seconds},
    )


async def postgres_is_ready(engine: AsyncEngine, timeout: float) -> bool:
    try:
        async with asyncio.timeout(timeout), engine.connect() as connection:
            await connection.execute(text("SELECT '[1,0]'::vector <=> '[1,0]'::vector"))
    except (SQLAlchemyError, PostgresError, OSError):
        return False
    return True
