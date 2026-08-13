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

# Any subdomain of these is trusted.
TRUSTED_SUFFIXES = (".gov.au", ".edu.au")

TRUSTED_DOMAINS: frozenset[str] = frozenset(
    {
        # Government
        "gov.au", "ato.gov.au", "fairwork.gov.au", "homeaffairs.gov.au",
        "immi.homeaffairs.gov.au", "vevo.homeaffairs.gov.au",
        "servicesaustralia.gov.au", "studyaustralia.gov.au", "moneysmart.gov.au",
        "scamwatch.gov.au", "healthdirect.gov.au", "mara.gov.au", "my.gov.au",
        "privatehealth.gov.au", "oaic.gov.au",
        # Property listings — the only housing-search sources Kip may link
        "realestate.com.au", "domain.com.au", "flatmates.com.au",
        # OSHC providers (government-approved insurers)
        "medibank.com.au", "bupa.com.au", "nib.com.au", "ahmoshc.com",
        "cbhsinternational.com.au", "allianzcare.com.au",
        # Major banks
        "commbank.com.au", "anz.com.au", "westpac.com.au", "nab.com.au",
        # Transport authorities not under .gov.au
        "translink.com.au", "adelaidemetro.com.au", "transportnsw.info",
        "transperth.wa.gov.au", "ptv.vic.gov.au",
        # Student services
        "unidays.com", "studentbeans.com",
        # Crisis support
        "lifeline.org.au", "beyondblue.org.au", "kidshelpline.com.au",
    }
)

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
    """Deterministic property-search links.

    Kip never invents listings. For any housing query we hand the student live
    search results on the trusted platforms instead.
    """
    slug = suburb.strip().lower().replace(" ", "-")
    plus = suburb.strip().lower().replace(" ", "+")
    st, pc, beds = state.strip().lower(), postcode.strip(), bedrooms.strip()

    rea_loc = ",+".join(x for x in (plus, st, pc) if x)
    dom_loc = "-".join(x for x in (slug, st, pc) if x)

    links = [
        {
            "name": "realestate.com.au",
            "url": (
                f"https://www.realestate.com.au/rent/property-house-with-{beds}-bedrooms-in-{rea_loc}/list-1"
                if beds
                else f"https://www.realestate.com.au/rent/in-{rea_loc}/list-1"
            ),
        },
        {
            "name": "domain.com.au",
            "url": (
                f"https://www.domain.com.au/rent/{dom_loc}/?bedrooms={beds}"
                if beds
                else f"https://www.domain.com.au/rent/{dom_loc}/"
            ),
        },
        {
            "name": "flatmates.com.au",
            "url": f"https://flatmates.com.au/rooms/{slug}" + (f"-{pc}" if pc else ""),
        },
    ]
    return links
