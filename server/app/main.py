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
    from . import websearch

    kb = knowledge()
    return {
        "status": "ok",
        "service": "Howdy Kip API",
        "model": settings.model,
        "web_search": websearch.enabled(),
        "searchable_domains": len(websearch.allowed_domains()),
        "knowledge_base_version": kb["_meta"]["version"],
        "knowledge_last_updated": kb["_meta"]["last_updated"],
    }


@health.get("/api/questions")
async def list_questions(module: str | None = None, q: str | None = None, limit: int = 40):
    """The seed bank of what students actually ask.

    Powers the UI's suggestion chips and doubles as the regression set the
    daily evolve job checks itself against.
    """
    import json
    from pathlib import Path

    path = Path(__file__).parents[2] / "knowledge" / "questions.json"
    if not path.is_file():
        return {"questions": [], "count": 0}

    data = json.loads(path.read_text(encoding="utf-8"))
    items = data["questions"]

    if module:
        items = [i for i in items if i["module"] == module]
    if q:
        needle = q.lower().strip()
        items = [i for i in items if needle in i["q"].lower()]

    return {
        "count": len(items),
        "total": data["_meta"]["count"],
        "questions": items[: max(1, min(limit, 200))],
    }


@health.get("/api/modules")
async def list_modules():
    """Topics for the UI — served from howdy.config.json so the front end and
    the model can never drift out of sync."""
    from .modules import MODULES

    return {
        "modules": [
            {
                "id": m.id,
                "name": m.name,
                "emoji": m.emoji,
                "colour": m.colour,
                "tagline": m.tagline,
                "examples": list(m.examples),
                "sources": list(m.sources),
            }
            for m in MODULES
        ]
    }


@health.get("/api/discounts")
async def discounts(postcode: str = "", state: str = "", category: str = ""):
    """Where to look for a student discount, for this student's own location.

    Deterministic and built server-side from howdy.config.json — no model is
    involved, so there is nothing here to hallucinate. It returns *where to
    look*, never what the discount is: percentages, fares and concession
    eligibility all change, and every URL is re-checked against the allowlist
    before it is returned.
    """
    from . import sources

    return sources.build_discount_guide(postcode=postcode, state=state, category=category)


app.include_router(health)


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    """Never leak a stack trace or an internal message to the client."""
    log.exception("unhandled_error path=%s", request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": "Something went wrong on our side. Please try again."},
    )
