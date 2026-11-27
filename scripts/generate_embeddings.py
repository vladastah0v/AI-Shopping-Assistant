import asyncio
import os
from argparse import ArgumentParser

from asyncpg import PostgresError
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.ai.embeddings.huggingface import SentenceTransformersProvider
from app.ai.embeddings.models import EMBEDDINGS_LOCK_KEY
from app.ai.embeddings.pipeline import Chunking, GenerationResult, generate_embeddings
from app.ai.embeddings.service import EmbeddingService
from app.core.config import Settings


async def run(
    provider: SentenceTransformersProvider, service: EmbeddingService, chunking: Chunking
) -> GenerationResult:
    settings = Settings()
    engine = create_async_engine(
        settings.database_url,
        poolclass=NullPool,
        connect_args={"timeout": settings.dependency_timeout_seconds},
    )
    try:
        async with engine.connect() as connection:
            # Closing the physical connection releases the session advisory lock.
            acquired = await connection.scalar(
                select(func.pg_try_advisory_lock(func.hashtextextended(EMBEDDINGS_LOCK_KEY, 0)))
            )
            await connection.commit()
            if not acquired:
                raise RuntimeError("Генерация embeddings уже выполняется для этой базы.")
            if provider.download_model:
                await provider.prepare()
            return await generate_embeddings(async_sessionmaker(connection), service, chunking)
    finally:
        await engine.dispose()


def main() -> None:
    parser = ArgumentParser(
        description="Сгенерировать embeddings для товаров и документов каталога."
    )
    parser.add_argument("--batch-size", type=int, default=8, help="Размер пакета от 1 до 64.")
    parser.add_argument("--chunk-size", type=int, default=800, help="Размер фрагмента в символах.")
    parser.add_argument(
        "--chunk-overlap", type=int, default=120, help="Перекрытие фрагментов в символах."
    )
    parser.add_argument(
        "--download-model", action="store_true", help="Разрешить загрузку закреплённой модели."
    )
    args = parser.parse_args()
    if not args.download_model:
        os.environ["HF_HUB_OFFLINE"] = "1"

    try:
        provider = SentenceTransformersProvider(download_model=args.download_model)
        service = EmbeddingService(provider, batch_size=args.batch_size)
        chunking = Chunking(args.chunk_size, args.chunk_overlap)
        result = asyncio.run(run(provider, service, chunking))
    except (ValueError, RuntimeError) as error:
        parser.exit(1, f"{error}\n")
    except (SQLAlchemyError, PostgresError, OSError):
        parser.exit(
            1, "Ошибка доступа к embeddings. Проверьте доступность PostgreSQL, роли и миграции.\n"
        )

    print(
        f"Проверено товаров — {result.products_read}, записано векторов — {result.products_written}. "
        f"Проверено документов — {result.documents_read}, записано фрагментов — {result.chunks_written}, "
        f"удалено устаревших фрагментов — {result.chunks_removed}."
    )


if __name__ == "__main__":
    main()
