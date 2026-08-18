"""Live web search, hard-restricted to official Australian sources.

The knowledge base carries stable facts (what a TFN is, how bond works). It
cannot carry volatile ones — this year's minimum wage, the current visa
application charge, a deadline that moved. For those Kip searches the live web.

The safety property that makes this acceptable: `allowed_domains` is set from
the same trusted-domain allowlist used to verify replies. Claude physically
cannot search anything else — not a blog, not a migration agent's marketing
page, not a forum. Search results can only come from ato.gov.au, fairwork.gov.au,
immi.homeaffairs.gov.au and the rest of the vetted list.

Two independent layers therefore guard every answer:
    1. Search input  — restricted to the allowlist by the API itself
    2. Reply output  — re-verified server-side by sources.verify_reply()
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from .appconfig import raw, trusted_domains

log = logging.getLogger("kip.websearch")

# Domains we let Claude search. Wildcards cover subdomains (help.ato.gov.au).
_EXTRA_WILDCARDS = ("*.gov.au", "*.edu.au")


def search_config() -> dict:
    return raw().get("web_search", {})


def enabled() -> bool:
    return bool(search_config().get("enabled", True))


def allowed_domains() -> list[str]:
    """The allowlist, as the API's web_search tool expects it."""
    return sorted(set(trusted_domains()) | set(_EXTRA_WILDCARDS))


def tool_definition() -> dict | None:
    """The web_search server tool, or None when search is switched off.

    Restricting `allowed_domains` is the whole safety argument — never remove it,
    and never widen it beyond the verified allowlist.
    """
    if not enabled():
        return None
    cfg = search_config()
    return {
        "type": cfg.get("tool_version", "web_search_20260209"),
        "name": "web_search",
        "max_uses": int(cfg.get("max_uses_per_answer", 3)),
        "allowed_domains": allowed_domains(),
        "user_location": {
            "type": "approximate",
            "country": "AU",
            "timezone": "Australia/Sydney",
        },
    }


# ── Reading what came back ───────────────────────────────────────────────


@dataclass
class SearchTrace:
    """What Kip actually looked at, for the UI's transparency panel."""

    queries: list[str] = field(default_factory=list)
    results: list[dict] = field(default_factory=list)   # {url, title, domain}
    errors: list[str] = field(default_factory=list)

    @property
    def used(self) -> bool:
        return bool(self.queries or self.results)


def _get(obj, key, default=None):
    """Blocks arrive as SDK objects or plain dicts depending on the path."""
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def trace_from_response(content_blocks) -> SearchTrace:
    """Pull queries and result URLs out of a completed response."""
    trace = SearchTrace()

    for block in content_blocks or []:
        btype = _get(block, "type")

        # The query Claude chose to run.
        if btype == "server_tool_use" and _get(block, "name") == "web_search":
            query = _get(_get(block, "input", {}) or {}, "query")
            if query:
                trace.queries.append(str(query)[:200])

        # What the search returned.
        elif btype == "web_search_tool_result":
            payload = _get(block, "content")

            # Errors arrive as a 200 with an error object in content, not as an
            # exception — a genuinely easy failure mode to miss.
            if isinstance(payload, dict) or (payload is not None and not isinstance(payload, list)):
                code = _get(payload, "error_code")
                if code:
                    trace.errors.append(str(code))
                    log.warning("web_search_error code=%s", code)
                    continue

            for item in payload or []:
                url = _get(item, "url")
                if not url:
                    continue
                from urllib.parse import urlparse

                host = (urlparse(url).hostname or "").lower().removeprefix("www.")
                trace.results.append({
                    "url": url,
                    "title": (_get(item, "title") or host)[:160],
                    "domain": host,
                })

    return trace


def merge_sources(cited, trace: SearchTrace) -> list[dict]:
    """Citations from the reply, plus any live pages the search actually opened.

    Search results are re-checked against the allowlist even though the API was
    already told to restrict them — defence in depth costs nothing here, and it
    means a change to the API's behaviour cannot quietly widen what we cite.
    """
    from .sources import is_trusted

    out: dict[str, dict] = {}
    for source in cited:
        d = source.as_dict() if hasattr(source, "as_dict") else dict(source)
        out[d["domain"]] = d

    for hit in trace.results:
        domain = hit["domain"]
        if domain not in out and is_trusted(domain):
            out[domain] = {"domain": domain, "url": hit["url"]}
    return list(out.values())
