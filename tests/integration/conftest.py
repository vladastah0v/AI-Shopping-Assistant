import os
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    database_url = os.environ.get("SHOPPING_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("SHOPPING_TEST_DATABASE_URL is required for catalog database tests")

    engine = create_async_engine(database_url, poolclass=NullPool, connect_args={"timeout": 5})
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            yield session
    finally:
        await engine.dispose()
