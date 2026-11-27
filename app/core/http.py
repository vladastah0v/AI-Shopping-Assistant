from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send


def validate_public_text(text: str) -> str:
    if any(ord(character) < 32 and character not in "\r\n\t" for character in text):
        raise ValueError("Удалите управляющие символы.")
    return text


class RequestLimitMiddleware:
    def __init__(self, app: ASGIApp, *, max_bytes: int = 16_384) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not scope["path"].startswith("/api/"):
            await self.app(scope, receive, send)
            return
        path = scope["path"]
        if scope["method"] not in ("POST", "PUT", "PATCH"):
            await self.app(scope, receive, self._private_response(path, send))
            return
        payload = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            if len(payload) + len(chunk) > self.max_bytes:
                response = JSONResponse(
                    {"detail": "Тело запроса превышает допустимый размер."}, 413
                )
                await response(scope, receive, self._private_response(path, send))
                return
            payload.extend(chunk)
            if not message.get("more_body"):
                break

        pending = True

        async def replay() -> Message:
            nonlocal pending
            if pending:
                pending = False
                return {"type": "http.request", "body": bytes(payload), "more_body": False}
            return await receive()

        await self.app(scope, replay, self._private_response(path, send))

    @staticmethod
    def _private_response(path: str, send: Send) -> Send:
        if not path.startswith("/api/v1/chat"):
            return send

        async def private(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = [
                    (name, value)
                    for name, value in message.get("headers", [])
                    if name != b"cache-control"
                ]
                message = {**message, "headers": [*headers, (b"cache-control", b"no-store")]}
            await send(message)

        return private
