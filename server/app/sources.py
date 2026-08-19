"""Source verification.

Kip may only cite domains on this allowlist. After every model response,
`verify_reply` extracts each URL, checks it, strips anything unverified, and
returns the surviving sources for the UI's "verified sources" panel.

This is deterministic server-side code. The model cannot talk its way past it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

from .appconfig import (
    discount_categories,
    discount_national,
    discount_states,
    eligibility_caution,
    housing_platforms,
    normalise_state,
    state_for_postcode,
    trusted_domains,
    trusted_suffixes,
)

# Loaded from howdy.config.json → sources.*  (edit the JSON, not this file)
TRUSTED_SUFFIXES: tuple[str, ...] = trusted_suffixes()
TRUSTED_DOMAINS: frozenset[str] = trusted_domains()

_URL_RE = re.compile(
    r"\bhttps?://[^\s<>()\"']+"
    r"|\b(?:[a-z0-9-]+\.)+(?:gov\.au|edu\.au|com\.au|org\.au|com|info|au)"
    r"(?:/[^\s<>()\"']*)?",
    re.I,
)

_TRAILING_PUNCT = re.compile(r"[.,;:!?)\]]+$")


@dataclass(frozen=True)
class Source:
    domain: str
    url: str

    def as_dict(self) -> dict:
        return {"domain": self.domain, "url": self.url}


def normalize(host: str) -> str:
    return (host or "").lower().removeprefix("www.")


def is_trusted(host: str) -> bool:
    domain = normalize(host)
    if not domain:
        return False
    if domain in TRUSTED_DOMAINS:
        return True
    if domain.endswith(TRUSTED_SUFFIXES):
        return True
    # A subdomain of an exact trusted domain (e.g. help.ato.gov.au).
    # The leading dot matters: it stops "realestate.com.au.phish.io" matching.
    return any(domain.endswith("." + t) for t in TRUSTED_DOMAINS)


def _host_of(candidate: str) -> str:
    try:
        with_scheme = candidate if candidate.lower().startswith(("http://", "https://")) else f"https://{candidate}"
        return urlparse(with_scheme).hostname or ""
    except ValueError:
        return ""


@dataclass
class VerifiedReply:
    reply: str
    sources: list[Source]
    verified: bool


def verify_reply(raw: str) -> VerifiedReply:
    """Strip every link that is not on the allowlist; collect the ones that are."""
    found: dict[str, Source] = {}
    all_verified = True

    def _sub(match: re.Match[str]) -> str:
        nonlocal all_verified
        cleaned = _TRAILING_PUNCT.sub("", match.group(0))
        host = _host_of(cleaned)
        if is_trusted(host):
            domain = normalize(host)
            if domain not in found:
                url = cleaned if cleaned.lower().startswith("http") else f"https://{cleaned}"
                found[domain] = Source(domain=domain, url=url)
            return match.group(0)
        all_verified = False
        return "[link removed — not a verified source]"

    reply = _URL_RE.sub(_sub, raw)
    return VerifiedReply(reply=reply, sources=list(found.values()), verified=all_verified)


def build_listing_links(
    suburb: str, state: str = "", postcode: str = "", bedrooms: str = ""
) -> list[dict]:
    """Deterministic property-search links, templated from howdy.config.json.

    Kip never invents listings. For any housing query we hand the student live
    search results on the trusted platforms instead.
    """
    fields = {
        "suburb_dash": suburb.strip().lower().replace(" ", "-"),
        "suburb_plus": suburb.strip().lower().replace(" ", "+"),
        "state": state.strip().lower(),
        "postcode": postcode.strip(),
        "beds": bedrooms.strip(),
    }

    links = []
    for platform in housing_platforms():
        template = platform["with_bedrooms"] if fields["beds"] else platform["without_bedrooms"]
        url = template.format(**fields)
        # Collapse separators left behind by an empty state or postcode.
        url = re.sub(r",\+(?=[,/])|,\+$", "", url)
        url = re.sub(r"-(?=[-/?])|-$", "", url)
        links.append({"name": platform["name"], "url": url})
    return links


# ── Discounts ────────────────────────────────────────────────────────────


def _trusted_link(entry: dict) -> dict | None:
    """Drop any configured link whose host is not on the allowlist.

    These links are built by us, so they never pass through `verify_reply`.
    Without this check a typo in howdy.config.json would be the one way an
    unverified URL could reach a student. Everything Kip emits is allowlisted,
    including the parts Kip did not write.
    """
    url = (entry or {}).get("url", "")
    if not is_trusted(_host_of(url)):
        return None
    out = {"name": entry.get("name", ""), "url": url}
    if entry.get("note"):
        out["note"] = entry["note"]
    return out


def build_discount_guide(postcode: str = "", state: str = "", category: str = "") -> dict:
    """Where to look for a student discount, for this student's actual location.

    Kip never states a discount amount from memory — percentages, fares and
    concession eligibility all change, and international students are not
    entitled to the same concessions in every state. So this returns *where to
    look*, the live-search phrases that reach the current page, and the
    eligibility warning when the category is one where being wrong costs money.
    """
    resolved = normalise_state(state) or state_for_postcode(postcode)
    states = discount_states()
    entry = states.get(resolved, {})

    local: list[dict] = []
    hints: list[str] = []
    for key in ("transport", "government"):
        source = entry.get(key)
        if not source:
            continue
        link = _trusted_link(source)
        if link:
            local.append(link)
            host = normalize(_host_of(source["url"]))
            if source.get("find"):
                hints.append(f"site:{host} {source['find']}")

    national: list[dict] = []
    for item in discount_national():
        link = _trusted_link(item)
        if link:
            national.append(link)

    categories = {c["id"]: c for c in discount_categories()}
    chosen = categories.get(category)
    needs_caution = chosen["eligibility_varies"] if chosen else True

    return {
        "state": resolved,
        "state_name": entry.get("state_name", ""),
        "known_state": bool(resolved),
        "category": chosen["id"] if chosen else "",
        "local": local,
        "national": national,
        "search_hints": hints,
        "caution": eligibility_caution() if needs_caution else "",
        "categories": [dict(c) for c in discount_categories()],
    }
