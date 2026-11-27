import asyncio
import logging
from collections.abc import Awaitable, Callable
from hashlib import sha256
from secrets import token_hex

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.observability import CACHE_HITS, CACHE_MISSES

logger = logging.getLogger(__name__)
_RELEASE = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('DEL', KEYS[1])
end
return 0
"""


def cache_key(namespace: str, payload: str) -> str:
    return f"shopping:{namespace}:{sha256(payload.encode()).hexdigest()}"


class RedisCache:
    def __init__(self, redis: Redis) -> None:
        self.redis = redis

    async def fetch[T](
        self,
        key: str,
        *,
        ttl: int,
        decode: Callable[[bytes], T],
        encode: Callable[[T], str],
        compute: Callable[[], Awaitable[T]],
        cacheable: Callable[[T], bool] = lambda _: True,
    ) -> T:
        namespace = key.split(":", 2)[1]
        namespace = namespace if namespace in {"search", "embeddings"} else "other"
        lock = f"{key}:lock"
        token = token_hex(16)
        acquired = False
        try:
            for attempt in range(7):
                raw = await self.redis.get(key)
                if raw is not None:
                    try:
                        result = decode(raw)
                        CACHE_HITS.labels(namespace).inc()
                        return result
                    except (ValueError, TypeError):
                        break
                if await self.redis.set(lock, token, ex=30, nx=True):
                    acquired = True
                    raw = await self.redis.get(key)
                    if raw is not None:
                        try:
                            await self.redis.eval(_RELEASE, 1, lock, token)
                            acquired = False
                            result = decode(raw)
                            CACHE_HITS.labels(namespace).inc()
                            return result
                        except (ValueError, TypeError):
                            break
                    break
                if attempt < 6:
                    await asyncio.sleep(0.05)
        except RedisError:
            logger.debug("Redis cache read failed")

        try:
            CACHE_MISSES.labels(namespace).inc()
            result = await compute()
            if acquired and cacheable(result):
                try:
                    await self.redis.set(key, encode(result), ex=ttl)
                except RedisError:
                    logger.debug("Redis cache write failed")
            return result
        finally:
            if acquired:
                try:
                    await self.redis.eval(_RELEASE, 1, lock, token)
                except RedisError:
                    logger.debug("Redis cache lock release failed")
