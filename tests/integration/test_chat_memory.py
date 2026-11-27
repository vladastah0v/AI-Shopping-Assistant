import os
from decimal import Decimal
from uuid import UUID

import pytest
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.intent import Intent, IntentQuery, infer_intent
from app.modules.catalog.schemas import ProductFilters
from app.modules.chat.memory import SessionMemory, merge_intent, referenced_products
from app.modules.chat.store import SessionStore, issue_owner_token, owner_hash


@pytest.mark.asyncio
async def test_session_ownership_and_versioned_memory(session: AsyncSession) -> None:
    url = os.environ.get("SHOPPING_TEST_REDIS_URL")
    if url is None:
        pytest.skip("SHOPPING_TEST_REDIS_URL is required for conversation cache tests")
    async with Redis.from_url(url) as redis:
        store = SessionStore(redis, ttl_seconds=60)
        owner = issue_owner_token()
        stranger = issue_owner_token()
        row = await store.create(session, owner, "Подбор техники")
        assert row.owner_token_hash == owner_hash(owner)
        assert row.owner_token_hash != owner
        assert await store.get(session, stranger, row.id) is None
        assert await store.list_sessions(session, stranger) == []
        assert await store.get(session, owner, row.id) is row
        assert (await store.load(session, row)).filters.max_price is None

        memory = SessionMemory(
            filters=ProductFilters(category_slug="laptops", max_price=Decimal("80000"))
        )
        store.update(row, memory)
        await session.flush()
        assert (await store.load(session, row)).filters.max_price == Decimal("80000")
        assert await store.load(session, row) == memory
        await store.clear(session, row)
        await session.flush()
        assert await store.load(session, row) == SessionMemory()


def test_followup_preserves_budget_and_resolves_ordinal_references() -> None:
    ids = [UUID(int=index) for index in range(1, 4)]
    state = SessionMemory(
        filters=ProductFilters(category_slug="laptops", max_price=80_000, spec=["ram_gb:gte:16"]),
        query="разработка",
        product_ids=ids,
    )
    result = merge_intent(infer_intent("А если с 32 ГБ оперативной памяти?"), state)
    assert result.filters.max_price == 80_000
    assert result.filters.category_slug == "laptops"
    assert result.filters.spec == ["ram_gb:gte:32"]
    assert result.query == "разработка"
    comparison = IntentQuery(intent=Intent.PRODUCT_COMPARISON)
    assert referenced_products("Сравни первый и третий", comparison, state) == [ids[0], ids[2]]
    assert referenced_products("Сравни первый и пятый", comparison, state) == []
