"""Where the model calls actually go.

Three places built their own Anthropic client with the key baked in, which
meant switching provider was three edits and a hope. This is the one place
that decides, so it is also the one place that can be tested.

**Read this before putting a gateway in front of Kip.**

Kip is unusually dependent on Anthropic *server-side* features, and a gateway
that normalises requests into a common schema will quietly break them:

    web_search + allowed_domains   the entire safety argument
    cache_control: ephemeral       worth about 4x on cost
    pause_turn                     multi-leg search turns
    server_tool_use blocks         how sources are read back
    cache_read_input_tokens        how answers are priced

The one that matters is the first. If `allowed_domains` does not survive the
round trip, Kip searches the open web instead of the sources we vouch for —
and it fails *silently*, because the citation verifier still strips the bad
links afterwards. You would see answer quality sag with nothing in the logs
to explain it. `python -m app.gateway check` exists to catch exactly that,
and it should be run against any gateway before it carries real traffic.

There is also a decision here that is not technical. A gateway sees every
question a student asks — including the ones about family violence and
underpayment. This codebase encrypts conversations on the assumption the
database will be stolen one day; routing the plaintext through a third party
undoes some of that. If you add one, it belongs in the privacy policy.

    direct     straight to Anthropic. The default, and the right one now.
    gateway    an OpenAI-compatible or Anthropic-compatible proxy
               (Portkey, OpenRouter, LiteLLM, your own).
"""

from __future__ import annotations

import logging
from functools import lru_cache

from .appconfig import raw

log = logging.getLogger(__name__)


def _settings():
    """Resolved lazily, on purpose.

    Importing config at module load pulls in pydantic and demands a full set
    of secrets, which makes this module unimportable in a test run — the same
    trap that already caught security.py, quota.py, answercache.py and
    budget.py. The routing decisions below are ours and should be checkable
    without an API key.
    """
    from .config import get_settings

    return get_settings()

DIRECT, GATEWAY = "direct", "gateway"


def _cfg() -> dict:
    return raw().get("llm", {})


def mode() -> str:
    return str(_cfg().get("mode", DIRECT))


def base_url() -> str | None:
    """None means talk to Anthropic directly."""
    if mode() != GATEWAY:
        return None
    url = _cfg().get("base_url") or ""
    return url or None


def extra_headers() -> dict:
    """Gateway routing headers, e.g. Portkey's x-portkey-* set.

    Values starting with `env:` are read from the environment, so a virtual
    key never lands in a config file that gets committed.
    """
    import os

    out = {}
    for k, v in (_cfg().get("headers") or {}).items():
        v = str(v)
        if v.startswith("env:"):
            v = os.environ.get(v[4:], "")
            if not v:
                log.warning("gateway_header_unset name=%s", k)
                continue
        out[k] = v
    return out


@lru_cache(maxsize=1)
def client():
    """The one Anthropic client the app uses.

    Cached, because building a client per request leaks connection pools —
    and because there should be exactly one answer to "where do calls go".
    """
    import anthropic

    settings = _settings()
    kwargs = {"api_key": settings.anthropic_key}
    if (url := base_url()):
        kwargs["base_url"] = url
        log.info("llm_via_gateway base_url=%s", url)
    if (headers := extra_headers()):
        kwargs["default_headers"] = headers
    return anthropic.AsyncAnthropic(**kwargs)


def describe() -> dict:
    """For the ops report. Never returns a key or a header value."""
    return {
        "mode": mode(),
        "base_url": base_url() or "api.anthropic.com",
        "routing_headers": sorted(extra_headers()),   # names only
        "model": _settings().model,
    }


# ── The check that matters ───────────────────────────────────────────────

PROBE = (
    "Reply with the exact words: gateway ok. Then, in one short sentence, "
    "say what the minimum wage in Australia is used for."
)


async def check() -> dict:
    """Send one real request and report what survived the round trip.

    This is not a ping. It asserts the four things a normalising gateway
    breaks, because a gateway that returns 200 while dropping
    `allowed_domains` is worse than one that fails outright — the failure is
    invisible until somebody notices Kip citing a blog.
    """
    from . import websearch
    from .costs import Usage, price

    settings = _settings()
    out: dict = {"provider": describe(), "checks": {}, "ok": False}

    tool = websearch.tool_definition()
    kwargs = {
        "model": settings.model,
        "max_tokens": 400,
        "system": [{
            "type": "text",
            "text": "You are a test harness. Answer briefly. " + ("x" * 4200),
            "cache_control": {"type": "ephemeral"},
        }],
        "messages": [{"role": "user", "content": PROBE}],
    }
    if tool is not None:
        kwargs["tools"] = [tool]

    try:
        response = await client().messages.create(**kwargs)
    except Exception as exc:  # noqa: BLE001
        out["error"] = f"{type(exc).__name__}: {exc}"
        return out

    usage = Usage.from_api(response.usage)
    text = "\n".join(b.text for b in response.content if getattr(b, "type", None) == "text")

    c = out["checks"]
    c["responded"] = bool(text)
    c["model_echoed"] = getattr(response, "model", "") or "(not reported)"

    # Prompt caching. A gateway that strips cache_control still answers, and
    # the bill quietly quadruples.
    cached = usage.cache_creation_input_tokens + usage.cache_read_input_tokens
    c["prompt_caching"] = cached > 0
    c["_caching_note"] = ("cache tokens reported" if cached else
                          "NO cache tokens — cache_control was dropped, expect ~4x cost")

    # Usage accounting. Without these fields costs.py prices everything at zero
    # and the budget guard never trips.
    c["usage_fields"] = usage.input_tokens > 0 and usage.output_tokens > 0
    c["_usage_note"] = ("input and output counted" if c["usage_fields"] else
                        "usage missing — costs.py would price every answer at $0 "
                        "and budget.py would never trip")

    # The one that matters.
    if tool is None:
        c["search_tool"] = None
        c["_search_note"] = "web search is switched off in config, nothing to check"
    else:
        accepted = any(getattr(b, "type", "") in ("server_tool_use", "web_search_tool_result")
                       for b in response.content)
        c["search_tool_accepted"] = accepted
        c["_search_note"] = (
            "the search tool was accepted" if accepted else
            "the model did not search — this probe may not have needed to, so run "
            "`python -m app.gateway check --search` for a question that must"
        )

    out["cost_usd"] = round(price(settings.model, usage).total, 6)
    out["ok"] = c["responded"] and c["usage_fields"]
    return out


SEARCH_PROBE = (
    "What is the current national minimum wage in Australia per hour? "
    "You must check an official source before answering."
)


async def check_search() -> dict:
    """Force a search and confirm the domain restriction actually applied.

    The strongest available evidence that `allowed_domains` survived: make the
    model search, then check every host it came back with against our own
    allowlist. A gateway that dropped the restriction will usually surface a
    host we never approved.
    """
    from . import websearch
    from .sources import _host_of, is_trusted

    settings = _settings()
    tool = websearch.tool_definition()
    if tool is None:
        return {"ok": False, "error": "web search is switched off in config"}

    kwargs = {
        "model": settings.model,
        "max_tokens": 700,
        "messages": [{"role": "user", "content": SEARCH_PROBE}],
        "tools": [tool],
    }
    try:
        response = await client().messages.create(**kwargs)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    trace = websearch.trace_from_response(response.content)
    hosts = sorted({_host_of(s.get("url", "")) for s in trace.sources if s.get("url")})
    outside = [h for h in hosts if h and not is_trusted(h)]

    return {
        "searched": trace.used,
        "queries": trace.queries,
        "hosts_returned": hosts,
        "hosts_outside_the_allowlist": outside,
        "ok": trace.used and not outside,
        "_note": (
            "every host came from the allowlist — the domain restriction survived"
            if trace.used and not outside else
            "THE SEARCH RESTRICTION DID NOT APPLY — do not send real traffic through "
            "this gateway" if outside else
            "the model did not search, so this proves nothing either way"
        ),
    }


def print_check(results: dict, search: dict | None = None) -> None:
    p = results["provider"]
    print(f"\n  LLM ROUTE — {p['mode']} via {p['base_url']}")
    print(f"  model: {p['model']}")
    if p["routing_headers"]:
        print(f"  routing headers: {', '.join(p['routing_headers'])}")
    if "error" in results:
        print(f"\n  ✗ {results['error']}\n")
        return

    print()
    for k, v in results["checks"].items():
        if k.startswith("_"):
            continue
        mark = "—" if v is None else ("✓" if v else "✗")
        print(f"  {mark} {k}: {v}")
        if (note := results["checks"].get("_" + k.split("_")[0] + "_note")):
            print(f"      {note}")
    print(f"\n  this probe cost ${results['cost_usd']:.6f}")

    if search is not None:
        print("\n  SEARCH RESTRICTION")
        if "error" in search:
            print(f"  ✗ {search['error']}")
        else:
            print(f"  hosts returned: {', '.join(search['hosts_returned']) or '(none)'}")
            print(f"  {'✓' if search['ok'] else '✗'} {search['_note']}")
    print()


if __name__ == "__main__":  # pragma: no cover
    import asyncio
    import sys

    async def main() -> None:
        res = await check()
        srch = await check_search() if "--search" in sys.argv else None
        print_check(res, srch)
        bad = not res["ok"] or (srch is not None and not srch["ok"])
        sys.exit(1 if bad else 0)

    asyncio.run(main())
