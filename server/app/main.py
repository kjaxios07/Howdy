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


@health.get("/api/quota")
async def quota_status(request: Request):
    """What's left today. Read-only — checking never spends a question."""
    from . import quota
    from .ratelimit import client_ip, hash_ip

    # Signed-in identity comes from the session; unauthenticated callers are
    # counted by hashed IP, same as the enforcement path.
    current = getattr(request.state, "user", None)
    subject = str(current.id) if current else hash_ip(client_ip(request)).hex()[:32]
    tier = quota.tier_for(
        signed_in=current is not None,
        subscribed=bool(getattr(current, "subscribed", False)),
    )
    return await quota.status(subject, tier)


def _probe_subject(request: Request) -> str:
    """Who the price is assigned to. Same identity rule as the quota counters:
    the session id when signed in, a hashed IP otherwise, so nothing durable
    is written about someone who never signed up."""
    from .ratelimit import client_ip, hash_ip

    current = getattr(request.state, "user", None)
    return str(current.id) if current else hash_ip(client_ip(request)).hex()[:32]


@health.get("/api/pricing")
async def pricing(request: Request):
    """What Kip Plus costs *this* student, and what it includes.

    The price comes from the probe, so it is stable for one person forever —
    the frontend must render this rather than hard-coding a number, or the
    same student will see two different prices and be right to distrust us.
    Displaying the paywall also counts an impression; that is the denominator
    of the whole experiment.
    """
    from . import priceprobe
    from .appconfig import raw

    subject = _probe_subject(request)
    await priceprobe.shown(subject)
    plan = raw().get("pricing", {})
    plus = plan.get("plus", {})
    return {
        "free": {
            "name": plan.get("free", {}).get("name", "Free"),
            "price": 0,
            "includes": plan.get("free", {}).get("includes", ""),
        },
        "plus": {
            "name": plus.get("name", "Kip Plus"),
            **priceprobe.offer(subject),
            "live": bool(plus.get("live", False)),
            "features": [
                {"name": f.get("name"), "what": f.get("what"), "status": f.get("status")}
                for f in plus.get("features", [])
            ],
        },
    }


@health.post("/api/pricing/intent")
async def pricing_intent(request: Request):
    """They tapped the button. Nothing is charged.

    This is the numerator. It records one anonymous increment against the
    price that person was shown — no row, no identity, no time finer than the
    day — and returns the honest "not open yet" copy for the screen.
    """
    from . import priceprobe

    price = await priceprobe.tapped(_probe_subject(request))
    return {
        "charged": False,
        "price": price,
        "message": (
            "Not open just yet — I'm still building this part. "
            "Leave your email and you'll be the first to know."
        ),
    }


@health.get("/api/budget")
async def budget_status():
    """Whether the product is running lean right now.

    Deliberately just the mode. The spend figures behind it are ours — a
    public endpoint that reports how close we are to a cap tells anyone who
    wants to push us over it exactly how far they have to go. `python -m
    app.costs report` and the answer_costs table are where the money lives.
    """
    from . import budget

    b = await budget.state()
    return {"mode": b.mode, "lean": b.mode != budget.NORMAL, "note": budget.message(b.mode)}


app.include_router(health)


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    """Never leak a stack trace or an internal message to the client."""
    log.exception("unhandled_error path=%s", request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": "Something went wrong on our side. Please try again."},
    )
