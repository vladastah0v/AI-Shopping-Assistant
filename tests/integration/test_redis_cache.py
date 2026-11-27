import asyncio
import os
from uuid import uuid4

import pytest
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import RedisCache, cache_key
from app.core.traffic import TrafficLimiter
from app.modules.catalog.models import Brand, Category, Product
from app.modules.catalog.revision import CatalogRevision
from app.modules.catalog.schemas import ProductFilters
from app.modules.search.schemas import SearchRequest
from app.modules.search.service import ProductSearch

pytestmark = pytest.mark.asyncio


def redis_url() -> str:
    result = os.environ.get("SHOPPING_TEST_REDIS_URL")
    if not result:
        pytest.skip("SHOPPING_TEST_REDIS_URL is required for Redis integration tests")
    return result


async def test_cache_coalesces_requests_and_rate_limits() -> None:
    namespace = uuid4().hex
    async with Redis.from_url(redis_url()) as redis:
        cache = RedisCache(redis)
        invocations = 0

        async def compute() -> str:
            nonlocal invocations
            invocations += 1
            await asyncio.sleep(0.05)
            return "данные"

        async def read() -> str:
            return await cache.fetch(
                cache_key("integration", namespace),
                ttl=5,
                encode=str,
                decode=bytes.decode,
                compute=compute,
            )

        assert await asyncio.gather(*(read() for _ in range(5))) == ["данные"] * 5
        assert invocations == 1

        traffic = TrafficLimiter(redis, per_minute=2, concurrency=1, lease_seconds=10)
        assert [await traffic.admitted(namespace, "test") for _ in range(3)] == [True, True, False]
        assert await traffic.acquire(namespace)
        try:
            assert not await traffic.acquire(namespace + "-second")
        finally:
            await traffic.release(namespace)


async def test_catalog_changes_invalidate_cached_cards(session: AsyncSession) -> None:
    suffix = uuid4().hex
    category = Category(slug=f"cache-{suffix}", name="Техника", description="")
    brand = Brand(name=f"Марка {suffix}", description="")
    product = Product(
        category=category,
        brand=brand,
        name="Монитор",
        sku=f"cache-{suffix}",
        description="Экран",
        price=6000,
        stock_quantity=1,
    )
    session.add(product)
    await session.flush()
    revision = await session.scalar(select(CatalogRevision.version))
    request = SearchRequest(
        query=product.sku, filters=ProductFilters(category_slug=category.slug, max_price=6500)
    )
    async with Redis.from_url(redis_url()) as redis:
        search = ProductSearch(None, cache=RedisCache(redis))
        original = await search.search(session, request, "keyword")
        assert len(original.items) == 1
        assert await search.search(session, request, "keyword") == original
        product.price = 7000
        await session.flush()
        assert await session.scalar(select(CatalogRevision.version)) > revision
        changed = await search.search(session, request, "keyword")
        assert changed.items == []
