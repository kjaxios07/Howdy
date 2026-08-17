"""Loader for howdy.config.json — the product's single source of truth.

Modules, trusted source domains, limits, privacy defaults and housing-search URL
templates all live in that file so they can be changed without touching Python.

Fail-fast is deliberate: the trusted-domain list is a security control. If the
config is missing or malformed we refuse to start rather than fall back to some
default allowlist nobody reviewed.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

# Search order: env override, repo root (dev), /etc/howdy (deployed), package dir.
_CANDIDATES = [
    os.environ.get("HOWDY_CONFIG_PATH", ""),
    str(Path(__file__).resolve().parents[2] / "howdy.config.json"),
    "/etc/howdy/howdy.config.json",
    str(Path(__file__).resolve().parent / "howdy.config.json"),
]


def _locate() -> Path:
    for candidate in _CANDIDATES:
        if candidate and Path(candidate).is_file():
            return Path(candidate)
    raise RuntimeError(
        "howdy.config.json not found. Looked in: "
        + ", ".join(c for c in _CANDIDATES if c)
    )


@dataclass(frozen=True)
class Module:
    id: str
    name: str
    emoji: str
    tagline: str
    colour: str
    examples: tuple[str, ...]
    sources: tuple[str, ...]


@lru_cache
def raw() -> dict:
    """The parsed config, validated enough to trust downstream."""
    path = _locate()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{path} is not valid JSON: {exc}") from exc

    for section in ("app", "model", "limits", "privacy", "sources", "modules"):
        if section not in data:
            raise RuntimeError(f"{path} is missing the required '{section}' section")

    if not data["sources"].get("trusted_domains"):
        raise RuntimeError(
            f"{path}: sources.trusted_domains is empty. Refusing to start — "
            "an empty allowlist would strip every citation from every answer."
        )

    if not data["modules"]:
        raise RuntimeError(f"{path}: no modules defined")

    return data


@lru_cache
def modules() -> tuple[Module, ...]:
    return tuple(
        Module(
            id=m["id"],
            name=m["name"],
            emoji=m.get("emoji", ""),
            tagline=m.get("tagline", ""),
            colour=m.get("colour", "14,124,102"),
            examples=tuple(m.get("examples", ())),
            sources=tuple(m.get("sources", ())),
        )
        for m in raw()["modules"]
    )


@lru_cache
def module_ids() -> frozenset[str]:
    return frozenset(m.id for m in modules())


@lru_cache
def trusted_domains() -> frozenset[str]:
    return frozenset(d.lower() for d in raw()["sources"]["trusted_domains"])


@lru_cache
def trusted_suffixes() -> tuple[str, ...]:
    return tuple(s.lower() for s in raw()["sources"].get("trusted_suffixes", ()))


@lru_cache
def housing_platforms() -> tuple[dict, ...]:
    return tuple(raw().get("housing_search", {}).get("platforms", ()))


def limits() -> dict:
    return raw()["limits"]


def privacy() -> dict:
    return raw()["privacy"]


def app_meta() -> dict:
    return raw()["app"]


def model_config() -> dict:
    return raw()["model"]
