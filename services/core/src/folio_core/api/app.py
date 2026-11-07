"""FastAPI application factory."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .. import __version__
from ..container import Container
from ..domain.errors import Conflict, InvalidInput, NotFound, PrivacyBlocked, Unavailable
from .routes import data, knowledge, labels, ledger, sources, system, views
from .security import TokenAuthMiddleware

ERROR_STATUS = {NotFound: 404, Conflict: 409, InvalidInput: 422, PrivacyBlocked: 403, Unavailable: 503}


def create_app(container: Container, token: str, start_background: bool = True) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):  # type: ignore[no-untyped-def]
        if start_background:
            container.start()
        yield
        if start_background:
            container.stop()

    app = FastAPI(title="Folio Core", version=__version__, lifespan=lifespan,
                  description="Local-first voice labeling & knowledge organization — core service.")
    app.state.container = container

    for exc_type, status in ERROR_STATUS.items():
        def handler(request: Request, exc: Exception, status: int = status) -> JSONResponse:
            return JSONResponse({"detail": str(exc)}, status_code=status)
        app.add_exception_handler(exc_type, handler)

    for module in (system, sources, knowledge, views, labels, ledger, data):
        app.include_router(module.router, prefix="/api")

    # Added last = outermost: CORS answers preflights before the token check runs.
    app.add_middleware(TokenAuthMiddleware, token=token,
                       allowed_origins=container.settings.allowed_origins)
    app.add_middleware(CORSMiddleware, allow_origins=list(container.settings.allowed_origins),
                       allow_methods=["*"], allow_headers=["*"])
    return app
