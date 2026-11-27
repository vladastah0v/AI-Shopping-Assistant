import asyncio
from argparse import ArgumentParser

from asyncpg import PostgresError
from sqlalchemy.exc import SQLAlchemyError

from app.ai.embeddings.huggingface import E5_SMALL
from app.ai.retrieval.indexing import rebuild_vector_indexes
from app.core.config import Settings
from app.core.database import create_database_engine


async def run(model: str, version: str) -> None:
    engine = create_database_engine(Settings())
    try:
        async with engine.begin() as connection:
            await rebuild_vector_indexes(connection, model, version)
    finally:
        await engine.dispose()


def main() -> None:
    parser = ArgumentParser(description="Перестроить HNSW-индексы для выбранной модели и версии.")
    parser.add_argument("--model", help="Идентификатор сохранённой embedding-модели.")
    parser.add_argument("--version", help="Версия сохранённых embeddings.")
    args = parser.parse_args()
    if (args.model is None) != (args.version is None):
        parser.error("Передайте --model и --version вместе.")

    model = args.model if args.model is not None else E5_SMALL.model
    version = args.version if args.version is not None else E5_SMALL.version
    try:
        asyncio.run(run(model, version))
    except (ValueError, RuntimeError) as error:
        parser.exit(1, f"{error}\n")
    except (SQLAlchemyError, PostgresError, OSError):
        parser.exit(
            1,
            "Переиндексация прервана. Проверьте соединение, ревизию схемы и блокировки PostgreSQL.\n",
        )

    print(f"Оба индекса HNSW перестроены для модели {model}, версия {version}.")


if __name__ == "__main__":
    main()
