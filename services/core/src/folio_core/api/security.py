"""Only the desktop shell may call the core (proposal: "Security and privacy").

* The server binds to 127.0.0.1 on a random port (see main.py).
* Every request needs the per-session token, as ``Authorization: Bearer <token>`` or, for
  browser elements that cannot set headers (EventSource, <video src>), a ``token`` query param.
* Requests that carry an Origin header must come from the app's own origins.
"""

from __future__ import annotations

import hmac
import json

from starlette.types import ASGIApp, Receive, Scope, Send

OPEN_PATHS = {"/api/health"}


class TokenAuthMiddleware:
    def __init__(self, app: ASGIApp, token: str, allowed_origins: tuple[str, ...]) -> None:
        self.app = app
        self.token = token.encode()
        self.allowed_origins = set(allowed_origins)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] in OPEN_PATHS or scope["method"] == "OPTIONS":
            await self.app(scope, receive, send)
            return
        headers = {k.decode().lower(): v.decode() for k, v in scope["headers"]}
        origin = headers.get("origin")
        if origin and origin not in self.allowed_origins:
            await _deny(send, 403, "origin not allowed")
            return
        supplied = ""
        auth = headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            supplied = auth[7:].strip()
        else:
            from urllib.parse import parse_qs

            supplied = (parse_qs(scope.get("query_string", b"").decode()).get("token") or [""])[0]
        if not hmac.compare_digest(supplied.encode(), self.token):
            await _deny(send, 401, "missing or invalid session token")
            return
        await self.app(scope, receive, send)


async def _deny(send: Send, status: int, detail: str) -> None:
    body = json.dumps({"detail": detail}).encode()
    await send({"type": "http.response.start", "status": status,
                "headers": [(b"content-type", b"application/json"),
                            (b"content-length", str(len(body)).encode())]})
    await send({"type": "http.response.body", "body": body})
