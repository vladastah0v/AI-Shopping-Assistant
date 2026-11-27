import json
import logging
from datetime import UTC, datetime
from time import perf_counter

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest
from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

HTTP_REQUESTS = Counter("shopping_http_requests", "HTTP requests.", ("method", "route", "status"))
HTTP_SECONDS = Histogram(
    "shopping_http_request_duration_seconds", "HTTP duration.", ("method", "route")
)
HTTP_ERRORS = Counter("shopping_http_errors", "HTTP client and server errors.", ("status",))
LLM_REQUESTS = Counter("shopping_llm_requests", "LLM calls.", ("mode", "status"))
LLM_SECONDS = Histogram("shopping_llm_generation_duration_seconds", "LLM duration.", ("mode",))
LLM_FAILURES = Counter("shopping_llm_failures", "LLM call failures.", ("mode",))
LLM_TOKENS = Counter("shopping_llm_tokens", "Observed Ollama tokens.", ("direction",))
RETRIEVAL_SECONDS = Histogram(
    "shopping_retrieval_duration_seconds", "Retrieval duration.", ("strategy",)
)
EMBEDDING_SECONDS = Histogram("shopping_embedding_duration_seconds", "Query embedding duration.")
TOOL_SECONDS = Histogram("shopping_tool_execution_duration_seconds", "Tool duration.", ("tool",))
TOOL_FAILURES = Counter("shopping_tool_failures", "Failed read-only tool calls.", ("tool",))
CACHE_HITS = Counter("shopping_cache_hits", "Redis cache hits.", ("namespace",))
CACHE_MISSES = Counter("shopping_cache_misses", "Redis cache misses.", ("namespace",))
ACTIVE_AI = Gauge("shopping_active_ai_requests", "Active AI requests in this process.")
REJECTED_AI = Counter("shopping_rejected_ai_requests", "Rejected AI requests.", ("status",))
INVALID_AI = Counter("shopping_invalid_ai_responses", "Invalid AI responses.", ("component",))

logger = logging.getLogger("app.http")
_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for field in ("method", "route", "status", "duration_ms", "tool", "error_type"):
            if hasattr(record, field):
                payload[field] = getattr(record, field)
        return json.dumps(payload, ensure_ascii=False)


def configure_logging() -> None:
    application_logger = logging.getLogger("app")
    if not any(
        isinstance(handler.formatter, JsonFormatter) for handler in application_logger.handlers
    ):
        handler = logging.StreamHandler()
        handler.setFormatter(JsonFormatter())
        application_logger.addHandler(handler)
        application_logger.setLevel(logging.INFO)
        application_logger.propagate = False


async def metrics_endpoint() -> Response:
    return Response(generate_latest(), headers={"Content-Type": CONTENT_TYPE_LATEST})


class MetricsMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] == "/metrics":
            await self.app(scope, receive, send)
            return
        started = perf_counter()
        status = 500

        async def timed_send(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, timed_send)
        finally:
            method = scope["method"] if scope["method"] in _METHODS else "OTHER"
            route = getattr(scope.get("route"), "path", "unmatched")
            duration = perf_counter() - started
            HTTP_REQUESTS.labels(method, route, status).inc()
            HTTP_SECONDS.labels(method, route).observe(duration)
            if status >= 400:
                HTTP_ERRORS.labels(status).inc()
            logger.info(
                "HTTP request completed",
                extra={
                    "method": method,
                    "route": route,
                    "status": status,
                    "duration_ms": round(duration * 1000, 3),
                },
            )
