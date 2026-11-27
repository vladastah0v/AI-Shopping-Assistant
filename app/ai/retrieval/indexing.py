from sqlalchemy import MetaData, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncConnection
from sqlalchemy.schema import CreateIndex, DropIndex

from app.ai.embeddings.models import EMBEDDINGS_LOCK_KEY, HNSW_INDEXES, hnsw_index


async def rebuild_vector_indexes(connection: AsyncConnection, model: str, version: str) -> None:
    """Replace the managed index pair inside the caller's transaction."""
    if any(not value.strip() or len(value) > 160 or "\x00" in value for value in (model, version)):
        raise ValueError("Укажите модель и версию длиной от 1 до 160 символов.")

    acquired = await connection.scalar(
        select(func.pg_try_advisory_xact_lock(func.hashtextextended(EMBEDDINGS_LOCK_KEY, 0)))
    )
    if not acquired:
        raise RuntimeError("В этой базе уже выполняется генерация или переиндексация.")

    await connection.execute(select(func.set_config("lock_timeout", "5s", True)))
    has_vectors = await connection.scalar(
        select(
            or_(
                *(
                    select(table.c.id)
                    .where(table.c.embedding_model == model, table.c.embedding_version == version)
                    .exists()
                    for table, _ in HNSW_INDEXES
                )
            )
        )
    )
    if not has_vectors:
        raise ValueError("Для указанной пары модели и версии в базе нет векторов.")

    replacements = []
    metadata = MetaData()
    for table, name in HNSW_INDEXES:
        table_copy = table.to_metadata(metadata, schema="public")
        current = next(index for index in table_copy.indexes if index.name == name)
        replacement = hnsw_index(table_copy, f"{name}_next", model, version)
        await connection.execute(CreateIndex(replacement))
        replacements.append((current, replacement))

    for current, replacement in replacements:
        await connection.execute(DropIndex(current))
        await connection.execute(
            text(f"ALTER INDEX public.{replacement.name} RENAME TO {current.name}")
        )
