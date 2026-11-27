import asyncio

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.config import Settings


def create_redis_client(settings: Settings) -> Redis:
    return Redis.from_url(
        str(settings.redis_url),
        socket_connect_timeout=settings.dependency_timeout_seconds,
        socket_timeout=settings.dependency_timeout_seconds,
    )


async def redis_is_ready(client: Redis, timeout: float) -> bool:
    try:
        async with asyncio.timeout(timeout):
            return bool(await client.ping())
    except (RedisError, OSError):
        return False
