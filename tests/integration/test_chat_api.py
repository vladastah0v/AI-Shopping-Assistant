import os
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import delete, select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.main import create_app
from app.modules.catalog.models import Brand, Category, Product

pytestmark = pytest.mark.asyncio


async def test_chat_turns_feedback_and_stream(session: AsyncSession) -> None:
    url = make_url(
        os.environ.get("SHOPPING_TEST_APP_DATABASE_URL") or os.environ["SHOPPING_TEST_DATABASE_URL"]
    )
    settings = Settings(
        _env_file=None,
        postgres_host=url.host,
        postgres_port=url.port,
        postgres_db=url.database,
        postgres_user=url.username,
        postgres_password=url.password,
        redis_url=os.environ.get("SHOPPING_TEST_REDIS_URL", "redis://127.0.0.1:6379/0"),
        dependency_timeout_seconds=5,
    )
    category = await session.scalar(select(Category).where(Category.slug == "laptops"))
    created_category = category is None
    if category is None:
        category = Category(name="Ноутбуки", slug="laptops", description="")
        session.add(category)
    brand = Brand(name=f"Бренд {uuid4()}", description="")
    products = [
        Product(
            category=category,
            brand=brand,
            name=f"Ноутбук {index}",
            sku=f"CHAT-{uuid4().hex[:7]}-{index}",
            description="Универсальный ноутбук",
            price=price,
            stock_quantity=2,
            specifications={"ram_gb": ram},
        )
        for index, (price, ram) in enumerate(
            [(60_000, 32), (70_000, 32), (50_000, 8), (95_000, 32)]
        )
    ]
    session.add_all(products)
    await session.commit()
    app = create_app(settings)
    try:
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test/api/v1/chat/"
            ) as client,
        ):
            created = await client.post("sessions", json={})
            assert created.status_code == 201
            data = created.json()
            path = f"sessions/{data['id']}"
            owner = {"Authorization": f"Bearer {data['access_token']}"}
            stranger = (await client.post("sessions", json={})).json()
            other = {"Authorization": f"Bearer {stranger['access_token']}"}
            assert (await client.get(path, headers=other)).status_code == 404
            assert (await client.get(path)).status_code == 401
            assert (await client.get("sessions", headers=owner)).json()[0]["id"] == data["id"]

            first = await client.post(
                f"{path}/messages",
                json={"content": "Подбери ноутбук до 80 000 рублей"},
                headers=owner,
            )
            assert first.status_code == 200
            second = await client.post(
                f"{path}/messages",
                json={"content": "А если с 32 ГБ оперативной памяти?"},
                headers=owner,
            )
            assert second.status_code == 200
            cards = second.json()["recommended_products"]
            assert len(cards) >= 2
            assert all(item["specifications"]["ram_gb"] >= 32 for item in cards)
            assert all(float(item["price"]) <= 80_000 for item in cards)

            streamed = await client.post(
                f"{path}/stream", json={"content": "Сравни первый и второй"}, headers=owner
            )
            assert streamed.status_code == 200
            assert streamed.headers["content-type"].startswith("text/event-stream")
            assert "event: result" in streamed.text
            assert '"compared_specifications":{"ram_gb":[32,32]}' in streamed.text

            history = (await client.get(f"{path}/messages", headers=owner)).json()
            assert [item["role"] for item in history] == ["user", "assistant"] * 3
            feedback = {"session_id": data["id"], "message_id": history[-1]["id"], "rating": 5}
            assert (await client.post("feedback", json=feedback, headers=other)).status_code == 404
            assert (await client.post("feedback", json=feedback, headers=owner)).json()[
                "rating"
            ] == 5
            assert (await client.delete(f"{path}/messages", headers=owner)).status_code == 204
            assert (await client.get(f"{path}/messages", headers=owner)).json() == []
            assert (await client.delete(path, headers=owner)).status_code == 204
            assert (
                await client.delete(f"sessions/{stranger['id']}", headers=other)
            ).status_code == 204
    finally:
        await session.execute(delete(Product).where(Product.id.in_([item.id for item in products])))
        await session.delete(brand)
        if created_category:
            await session.delete(category)
        await session.commit()
