"""Bound requests before JSON parsing; apply safe headers to errors as well as success."""

import json
import logging
from uuid import uuid4

import anyio
from starlette.datastructures import Headers, MutableHeaders
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.config import Settings

logger = logging.getLogger("nearperk.security")
logger.setLevel(logging.INFO)


class PayloadTooLarge(Exception):
    pass


class SecurityBoundary:
    def __init__(self, app: ASGIApp, settings: Settings):
        self.app, self.settings = app, settings

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = str(uuid4())
        scope.setdefault("state", {})["request_id"] = request_id
        headers = Headers(scope=scope)
        started = False

        async def secure_send(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
                out = MutableHeaders(scope=message)
                out["X-Request-ID"] = request_id
                out["X-Content-Type-Options"] = "nosniff"
                out["X-Frame-Options"] = "DENY"
                out["Referrer-Policy"] = "no-referrer"
                out["Permissions-Policy"] = "camera=(self), geolocation=(self), microphone=()"
                out["Content-Security-Policy"] = (
                    "default-src 'none'; frame-ancestors 'none'; base-uri 'none'"
                    if scope["path"].startswith("/api/")
                    else "frame-ancestors 'none'; base-uri 'none'"
                )
                if scope["path"].startswith("/api/") or message["status"] >= 400:
                    out["Cache-Control"] = "no-store"
                if self.settings.app_env not in {"development", "test"}:
                    out["Strict-Transport-Security"] = "max-age=31536000"
            await send(message)

        async def reject(status: int, code: str, message: str) -> None:
            logger.warning(json.dumps({"event": code, "request_id": request_id, "status": status}))
            response = JSONResponse(
                {"error": {"code": code, "message": message, "request_id": request_id}},
                status_code=status,
            )
            origin = headers.get("origin")
            if origin in self.settings.cors_origins:
                response.headers["Access-Control-Allow-Origin"] = origin
                response.headers["Access-Control-Allow-Credentials"] = "true"
                response.headers["Vary"] = "Origin"
            await response(scope, receive, secure_send)

        if len(scope.get("query_string", b"")) > 4096:
            await reject(414, "REQUEST_TOO_LONG", "The request URL is too long.")
            return
        # Header limits also bound authorization tokens and attacker-controlled cookies.
        if sum(len(k) + len(v) for k, v in scope.get("headers", [])) > 16384:
            await reject(431, "HEADERS_TOO_LARGE", "Request headers are too large.")
            return
        if len(headers.getlist("host")) > 1 or (
            headers.get("transfer-encoding") and headers.get("content-length")
        ):
            await reject(400, "AMBIGUOUS_HEADERS", "Ambiguous request headers.")
            return
        values = headers.getlist("content-length")
        try:
            if len(values) > 1 or (values and (not values[0].isascii() or not values[0].isdigit())):
                raise ValueError
            length = int(values[0]) if values else 0
        except ValueError:
            await reject(400, "INVALID_LENGTH", "Invalid request length.")
            return
        if length > self.settings.max_request_bytes:
            await reject(413, "REQUEST_TOO_LARGE", "The request body is too large.")
            return
        if headers.get("content-encoding", "identity").lower() != "identity":
            await reject(
                415, "UNSUPPORTED_ENCODING", "Compressed request bodies are not supported."
            )
            return
        body = bytearray()
        try:
            with anyio.fail_after(self.settings.request_body_timeout_seconds):
                while True:
                    message = await receive()
                    if message["type"] == "http.disconnect":
                        return
                    body.extend(message.get("body", b""))
                    if len(body) > self.settings.max_request_bytes:
                        raise PayloadTooLarge
                    if not message.get("more_body", False):
                        break
        except PayloadTooLarge:
            await reject(413, "REQUEST_TOO_LARGE", "The request body is too large.")
            return
        except TimeoutError:
            await reject(408, "REQUEST_TIMEOUT", "The request body took too long to arrive.")
            return
        if values and length != len(body):
            await reject(400, "INVALID_LENGTH", "Request length does not match its body.")
            return
        content_type = headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if (
            body
            and scope["path"].startswith("/api/")
            and not (
                content_type == "application/json"
                or content_type.startswith("application/")
                and content_type.endswith("+json")
            )
        ):
            await reject(
                415,
                "UNSUPPORTED_MEDIA",
                "Only JSON request bodies are supported. File uploads are unavailable.",
            )
            return
        consumed = False

        async def replay() -> Message:
            nonlocal consumed
            if not consumed:
                consumed = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        try:
            await self.app(scope, replay, secure_send)
        except Exception as exc:
            if started:
                raise
            logger.error(
                json.dumps(
                    {
                        "event": "UNHANDLED_ERROR",
                        "request_id": request_id,
                        "exception_type": type(exc).__name__,
                    }
                )
            )
            await reject(500, "INTERNAL_ERROR", "Unable to complete the request. Try again later.")
