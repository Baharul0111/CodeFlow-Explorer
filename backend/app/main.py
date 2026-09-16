"""FastAPI application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from app.api.errors import install_error_handlers
from app.api.routes_health import router as health_router
from app.config import Settings, get_settings
from app.logging_setup import configure_logging, get_logger
from app.models.db import Database

log = get_logger(__name__)

SECURE_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Cache-Control": "no-store",
}


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, json_output=settings.app_env == "prod")

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        db = Database(settings.database_url)
        await db.create_all()
        app.state.db = db
        settings.workspace_dir.mkdir(parents=True, exist_ok=True)
        log.info("startup", env=settings.app_env, llm_mode=settings.llm_mode)
        try:
            yield
        finally:
            await db.dispose()
            log.info("shutdown")

    app = FastAPI(title="CodeFlow Explorer API", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.frontend_origin],
        allow_credentials=False,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "X-Session-Token", "Last-Event-ID"],
        expose_headers=["Content-Disposition"],
    )

    @app.middleware("http")
    async def secure_headers(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        for key, value in SECURE_HEADERS.items():
            response.headers.setdefault(key, value)
        return response

    install_error_handlers(app)
    app.include_router(health_router)
    return app


app = create_app()
