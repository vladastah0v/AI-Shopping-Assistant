import asyncio

from asyncpg import PostgresError
from sqlalchemy import MetaData, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import Settings


class Base(DeclarativeBase):
    metadata = MetaData(
        naming_convention={
            "pk": "pk_%(table_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "uq": "uq_%(table_name)s_%(column_0_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
            "ix": "ix_%(table_name)s_%(column_0_name)s",
        }
    )


def create_database_engine(settings: Settings) -> AsyncEngine:
    return create_async_engine(
        settings.database_url,
        pool_pre_ping=True,
        hide_parameters=True,
        connect_args={"timeout": settings.dependency_timeout_seconds},
    )


async def postgres_is_ready(engine: AsyncEngine, timeout: float) -> bool:
    try:
        async with asyncio.timeout(timeout), engine.connect() as connection:
            await connection.execute(text("SELECT '[1,0]'::vector <=> '[1,0]'::vector"))
    except (SQLAlchemyError, PostgresError, OSError):
        return False
    return True
