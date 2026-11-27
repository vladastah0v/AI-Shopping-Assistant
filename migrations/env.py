import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import Connection
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.ai.embeddings import models as embedding_models  # noqa: F401 -- Register embedding tables.
from app.core.config import Settings
from app.modules.catalog import models as catalog_models
from app.modules.chat import models as chat_models  # noqa: F401 -- Register conversation tables.

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def run_migrations_offline() -> None:
    context.configure(
        dialect_name="postgresql",
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        target_metadata=catalog_models.Base.metadata,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=catalog_models.Base.metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    settings = Settings()
    engine = create_async_engine(
        settings.database_url,
        poolclass=NullPool,
        connect_args={"timeout": settings.dependency_timeout_seconds},
    )
    try:
        async with engine.connect() as connection:
            await connection.run_sync(run_migrations)
    finally:
        await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
