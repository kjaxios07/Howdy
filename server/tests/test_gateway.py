"""Tests for where model calls go.

The reason this module exists is one failure mode: a gateway that returns
HTTP 200 while silently dropping `allowed_domains`. Kip then searches the
open web, the citation verifier strips the bad links afterwards, and all you
see is answer quality sagging with nothing in the logs. Every test here is
downstream of that.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import gateway  # noqa: E402


def run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


# ── Configuration ────────────────────────────────────────────────────────

def test_direct_is_the_default():
    """Anything else is a decision somebody has to make on purpose."""
    assert gateway.mode() == gateway.DIRECT
    assert gateway.base_url() is None


def test_a_gateway_needs_an_explicit_base_url(monkeypatch):
    monkeypatch.setattr(gateway, "_cfg", lambda: {"mode": "gateway", "base_url": ""})
    assert gateway.base_url() is None, "gateway mode with no URL must not silently work"

    monkeypatch.setattr(gateway, "_cfg",
                        lambda: {"mode": "gateway", "base_url": "https://api.portkey.ai/v1"})
    assert gateway.base_url() == "https://api.portkey.ai/v1"


def test_direct_mode_ignores_a_configured_base_url(monkeypatch):
    """Switching back to direct must actually go direct, not keep pointing at
    a proxy because the URL is still sitting in the file."""
    monkeypatch.setattr(gateway, "_cfg",
                        lambda: {"mode": "direct", "base_url": "https://api.portkey.ai/v1"})
    assert gateway.base_url() is None


# ── Keys never land in the config file ───────────────────────────────────

def test_env_headers_are_read_from_the_environment(monkeypatch):
    monkeypatch.setenv("PORTKEY_API_KEY", "pk-secret-value")
    monkeypatch.setattr(gateway, "_cfg", lambda: {
        "mode": "gateway",
        "headers": {"x-portkey-api-key": "env:PORTKEY_API_KEY",
                    "x-portkey-provider": "anthropic"},
    })
    h = gateway.extra_headers()
    assert h["x-portkey-api-key"] == "pk-secret-value"
    assert h["x-portkey-provider"] == "anthropic"


def test_an_unset_env_header_is_dropped_not_sent_empty(monkeypatch):
    """Sending an empty key reads as an auth failure at the far end, which is
    a confusing way to discover the variable was never exported."""
    monkeypatch.delenv("PORTKEY_API_KEY", raising=False)
    monkeypatch.setattr(gateway, "_cfg", lambda: {
        "mode": "gateway", "headers": {"x-portkey-api-key": "env:PORTKEY_API_KEY"},
    })
    assert "x-portkey-api-key" not in gateway.extra_headers()


def test_describe_never_leaks_a_header_value(monkeypatch):
    """describe() feeds the ops report. It may say which headers are set and
    must never say what they contain."""
    monkeypatch.setenv("PORTKEY_API_KEY", "pk-secret-value")
    monkeypatch.setattr(gateway, "_cfg", lambda: {
        "mode": "gateway", "base_url": "https://api.portkey.ai/v1",
        "headers": {"x-portkey-api-key": "env:PORTKEY_API_KEY"},
    })
    monkeypatch.setattr(gateway, "_settings",
                        lambda: type("S", (), {"model": "claude-sonnet-5"})())
    d = gateway.describe()
    assert d["routing_headers"] == ["x-portkey-api-key"]
    assert "pk-secret-value" not in str(d)


# ── The check, which is the point of the module ──────────────────────────

def test_the_check_asserts_the_four_things_a_gateway_breaks():
    """Not a ping. A gateway that answers while dropping cache_control or the
    usage fields is worse than one that errors, because nothing tells you."""
    src = Path(gateway.__file__).read_text()
    for signal in ("cache_creation_input_tokens", "cache_read_input_tokens",
                   "server_tool_use", "allowed_domains"):
        assert signal in src, signal


def test_the_search_check_compares_hosts_against_our_own_allowlist():
    """The strongest evidence available that the domain restriction survived:
    make it search, then check what came back against is_trusted."""
    src = Path(gateway.__file__).read_text()
    assert "is_trusted" in src
    assert "hosts_outside_the_allowlist" in src


def test_a_failed_probe_reports_rather_than_raising(monkeypatch):
    """A gateway that is simply down should produce a readable line in the
    preflight, not a traceback in the middle of a deploy."""
    class Broken:
        messages = None
        async def create(self, **kw):
            raise RuntimeError("connection refused")
    b = Broken(); b.messages = b

    monkeypatch.setattr(gateway, "client", lambda: b)
    monkeypatch.setattr(gateway, "_settings",
                        lambda: type("S", (), {"model": "claude-sonnet-5",
                                               "anthropic_key": "x"})())
    out = run(gateway.check())
    assert out["ok"] is False
    assert "connection refused" in out["error"]


def test_the_probe_costs_almost_nothing():
    """It has to be cheap enough to run on every deploy without thinking."""
    src = Path(gateway.__file__).read_text()
    assert "max_tokens" in src
    assert '"max_tokens": 400' in src or "max_tokens=400" in src


# ── One client, one decision ─────────────────────────────────────────────

def test_nothing_builds_its_own_anthropic_client():
    """Three modules used to construct their own with the key baked in, which
    meant switching provider was three edits and a hope — and meant no single
    place could be tested for whether the restriction survived."""
    app = Path(gateway.__file__).parent
    offenders = [
        p.name for p in app.rglob("*.py")
        if p.name != "gateway.py" and "AsyncAnthropic(" in p.read_text()
    ]
    assert not offenders, f"these bypass the gateway: {offenders}"


def test_the_client_is_built_once():
    """A client per request leaks connection pools."""
    assert hasattr(gateway.client, "cache_clear"), "client() is not memoised"


def test_the_privacy_tradeoff_is_written_down():
    """A gateway sees every question a student asks, including the ones about
    family violence. That is a privacy decision, not just an infra one, and it
    should not be discoverable only by reading the request logs."""
    src = Path(gateway.__file__).read_text().lower()
    assert "privacy" in src or "sees every question" in src
