"""Application entry point."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.middleware.sessions import SessionMiddleware

from .config import get_settings
from .prompt import knowledge
from .routers import auth, chat, conversations, me
from .retention import retention_sweep_forever

settings = get_settings()
logging.basicConfig(level=settings.log_level)
log = logging.getLogger("kip")

if settings.sentry_dsn:
    import sentry_sdk

    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        traces_sample_rate=0.1,
        send_default_pii=False,          # never ship user content to Sentry
        before_send=lambda event, hint: _scrub(event),
    )


def _scrub(event: dict) -> dict:
    """Belt-and-braces: strip request bodies before anything leaves the box."""
    if "request" in event:
        event["request"].pop("data", None)
        event["request"].pop("cookies", None)
    return event


@asynccontextmanager
async def lifespan(app: FastAPI):
    import asyncio

    knowledge()  # fail fast at boot if the knowledge base is missing or invalid
    sweeper = asyncio.create_task(retention_sweep_forever())
    log.info("kip_started model=%s env=%s", settings.model, settings.env)
    try:
        yield
    finally:
        sweeper.cancel()


app = FastAPI(
    title="Howdy / Kip API",
    version="2.0.0",
    lifespan=lifespan,
    docs_url="/api/docs" if settings.env != "production" else None,
    redoc_url=None,
    openapi_url="/api/openapi.json" if settings.env != "production" else None,
)

# Authlib's Starlette client needs a signed session cookie to carry OAuth state.
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.cookie_secret,
    session_cookie="hoauth",
    https_only=True,
    same_site="lax",
    max_age=600,
)

app.include_router(auth.router)
app.include_router(chat.router)
app.include_router(conversations.router)
app.include_router(me.router)

health = APIRouter(tags=["ops"])


@health.get("/api/health")
async def healthcheck():
    kb = knowledge()
    return {
        "status": "ok",
        "service": "Howdy Kip API",
        "model": settings.model,
        "knowledge_base_version": kb["_meta"]["version"],
        "knowledge_last_updated": kb["_meta"]["last_updated"],
    }


app.include_router(health)


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    """Never leak a stack trace or an internal message to the client."""
    log.exception("unhandled_error path=%s", request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": "Something went wrong on our side. Please try again."},
    )
