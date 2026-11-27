import asyncio
from argparse import ArgumentParser
from collections.abc import Callable, Coroutine
from typing import Any

from asyncpg import PostgresError
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.database import create_database_engine


def run_catalog_command[T](
    parser: ArgumentParser, operation: Callable[[AsyncSession], Coroutine[Any, Any, T]]
) -> T:
    async def run() -> T:
        engine = create_database_engine(Settings())
        try:
            async with AsyncSession(engine, expire_on_commit=False) as session, session.begin():
                return await operation(session)
        finally:
            await engine.dispose()

    try:
        return asyncio.run(run())
    except ValueError as error:
        parser.error(str(error))
    except IntegrityError:
        parser.exit(1, "База отклонила запись. Проверьте уникальность и ограничения каталога.\n")
    except (SQLAlchemyError, PostgresError, OSError):
        parser.exit(
            1, "Операция с каталогом прервана. Проверьте схему, доступность базы и права роли.\n"
        )
