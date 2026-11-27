from hashlib import sha256
from secrets import token_hex

from redis.asyncio import Redis
from redis.exceptions import RedisError
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

_WINDOW = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then redis.call('EXPIRE', KEYS[1], 60) end
return count
"""
_ACQUIRE = """
local time = redis.call('TIME')
local now = tonumber(time[1])
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now)
if redis.call('ZCARD', KEYS[1]) >= tonumber(ARGV[1]) then return 0 end
redis.call('ZADD', KEYS[1], now + tonumber(ARGV[2]), ARGV[3])
redis.call('EXPIRE', KEYS[1], ARGV[2])
return 1
"""


class TrafficLimiter:
    def __init__(
        self, redis: Redis, *, per_minute: int, concurrency: int, lease_seconds: int
    ) -> None:
        self.redis = redis
        self.per_minute = per_minute
        self.concurrency = concurrency
        self.lease_seconds = lease_seconds

    async def admitted(self, identity: str, group: str) -> bool:
        subject = sha256(identity.encode()).hexdigest()
        count = await self.redis.eval(_WINDOW, 1, f"shopping:rate:v1:{group}:{subject}")
        return count <= self.per_minute

    async def acquire(self, token: str) -> bool:
        return bool(
            await self.redis.eval(
                _ACQUIRE, 1, "shopping:active_ai:v1", self.concurrency, self.lease_seconds, token
            )
        )

    async def release(self, token: str) -> None:
        await self.redis.zrem("shopping:active_ai:v1", token)


class TrafficMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        limiter = getattr(scope["app"].state, "traffic", None)
        path = scope["path"]
        chat = path == "/api/v1/chat" or path.startswith("/api/v1/chat/")
        search = path.startswith("/api/v1/search/")
        if limiter is None or not (chat or search):
            await self.app(scope, receive, send)
            return
        identity = scope["client"][0] if scope.get("client") else "unknown"
        heavy = (
            chat
            and scope["method"] == "POST"
            and path.rstrip("/").endswith(("/messages", "/stream"))
        )
        lease = token_hex(16)
        active = False
        error = None
        try:
            if not await limiter.admitted(identity, "chat" if chat else "search"):
                error = JSONResponse(
                    {"detail": "Превышен лимит запросов."}, 429, headers={"Retry-After": "60"}
                )
            elif heavy:
                active = await limiter.acquire(lease)
                if not active:
                    error = JSONResponse(
                        {"detail": "Консультант обрабатывает другие запросы."},
                        429,
                        headers={"Retry-After": "2"},
                    )
        except RedisError:
            if chat:
                error = JSONResponse({"detail": "Консультант временно недоступен."}, 503)
        if error is not None:
            await error(scope, receive, send)
            return
        try:
            await self.app(scope, receive, send)
        finally:
            if active:
                try:
                    await limiter.release(lease)
                except RedisError:
                    pass
