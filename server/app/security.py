"""Input defence: sanitisation, PII detection, prompt-injection detection.

Deliberately dependency-free — no database, no Redis, no secrets. These are pure
functions so they can be unit-tested in isolation and reasoned about on their own.
Rate limiting and IP hashing need infrastructure, so they live in ratelimit.py.

Order of operations on every chat request:
    sanitise -> PII guard -> injection guard -> rate limit -> model

The PII guard runs *before* the model call by design. A message containing a TFN
or passport number is refused, not forwarded — so those values never reach
Anthropic, never enter a prompt, and never get written to our database.
"""

from __future__ import annotations

import re

MAX_MESSAGE_CHARS = 800

# ── Sanitisation ─────────────────────────────────────────────────────────

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def sanitize_message(raw: str | None, max_chars: int = MAX_MESSAGE_CHARS) -> str:
    if not isinstance(raw, str):
        return ""
    cleaned = _CONTROL.sub("", raw).replace("<", "").replace(">", "")
    return cleaned.strip()[:max_chars]


# ── PII guard ────────────────────────────────────────────────────────────
# Heuristics, tuned to over-refuse rather than under-refuse. The system prompt
# carries a second layer (rule 4) for anything these patterns miss.

PII_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("tfn_or_id", re.compile(r"\b\d{3}[ -]?\d{3}[ -]?\d{2,3}\b")),
    ("card", re.compile(r"\b(?:\d[ -]?){13,19}\b")),
    ("passport", re.compile(r"\b[A-Za-z]{1,2}\d{7,8}\b")),
    ("email", re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")),
    ("au_mobile", re.compile(r"\b(?:\+?61|0)[ -]?4\d{2}[ -]?\d{3}[ -]?\d{3}\b")),
    ("medicare", re.compile(r"\b\d{4}[ -]?\d{5}[ -]?\d\b")),
]


def detect_pii(text: str) -> str | None:
    """Return the name of the first matching pattern, or None."""
    for name, pattern in PII_PATTERNS:
        if pattern.search(text):
            return name
    return None


PII_RESPONSE = (
    "Whoa — it looks like your message might contain personal details (a TFN, passport, "
    "card, Medicare, phone number or email). For your safety I never process or store "
    "personal information, so I haven't read that message.\n\n"
    "Please ask again **without** any personal identifiers — for example, "
    '"How do I apply for a TFN?" rather than sharing the number itself. 🛡️'
)


# ── Prompt-injection guard ───────────────────────────────────────────────

INJECTION_PATTERNS = [
    re.compile(p, re.I)
    for p in (
        r"ignore\s+(all\s+)?(previous|prior|your)\s+instructions",
        r"system\s*prompt",
        r"you\s+are\s+now\s+",
        r"pretend\s+(to\s+be|you\s+are)",
        r"act\s+as\s+(?!a student|an? (international|new|migrant))",
        r"jailbreak",
        r"dan\s+mode",
        r"disregard\s+(all\s+)?rules",
        r"override\s+(your\s+)?instructions",
        r"reveal\s+(your\s+)?(prompt|instructions|system)",
        r"repeat\s+(the\s+)?(text\s+)?above",
    )
]


def detect_injection(text: str) -> bool:
    return any(p.search(text) for p in INJECTION_PATTERNS)


INJECTION_RESPONSE = (
    "G'day! I'm Kip, your companion for life in Australia. I can help with visas, work "
    "rights, tax, housing, healthcare, banking and more — always with official sources. "
    "What would you like to know?"
)
