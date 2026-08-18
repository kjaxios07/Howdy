"""Tests for the live-search layer.

The security property under test: Claude can only ever search the vetted
allowlist. If these fail, an answer could cite a migration agent's marketing
page or a forum — exactly what this product exists to protect students from.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import sources, websearch  # noqa: E402


# ── Tool definition ──────────────────────────────────────────────────────

def test_tool_is_domain_restricted():
    tool = websearch.tool_definition()
    assert tool is not None, "web search should be enabled in the shipped config"
    assert tool["name"] == "web_search"
    assert tool["allowed_domains"], "an unrestricted web_search tool must never ship"


def test_allowlist_matches_citation_allowlist():
    """Search input and citation output must be governed by the same list."""
    allowed = set(websearch.allowed_domains())
    for domain in sources.TRUSTED_DOMAINS:
        assert domain in allowed, f"{domain} is citable but not searchable"


def test_allowlist_contains_no_untrusted_domain():
    for domain in websearch.allowed_domains():
        if domain.startswith("*."):
            continue  # wildcard suffixes are checked separately
        assert sources.is_trusted(domain), f"{domain} is searchable but not citable"


def test_max_uses_is_capped():
    tool = websearch.tool_definition()
    assert 1 <= tool["max_uses"] <= 5, "an uncapped search budget is a cost incident"


def test_search_is_scoped_to_australia():
    tool = websearch.tool_definition()
    assert tool["user_location"]["country"] == "AU"


# ── Response parsing ─────────────────────────────────────────────────────

def test_trace_extracts_queries_and_results():
    blocks = [
        {"type": "server_tool_use", "name": "web_search",
         "input": {"query": "national minimum wage 2026"}},
        {"type": "web_search_tool_result", "content": [
            {"url": "https://www.fairwork.gov.au/pay-and-wages/minimum-wages",
             "title": "Minimum wages"},
        ]},
        {"type": "text", "text": "The minimum wage is ..."},
    ]
    trace = websearch.trace_from_response(blocks)
    assert trace.used is True
    assert trace.queries == ["national minimum wage 2026"]
    assert trace.results[0]["domain"] == "fairwork.gov.au"


def test_trace_handles_search_errors_without_raising():
    """Search failures arrive as a 200 with an error object — easy to miss."""
    blocks = [
        {"type": "server_tool_use", "name": "web_search", "input": {"query": "x"}},
        {"type": "web_search_tool_result", "content": {"error_code": "max_uses_exceeded"}},
    ]
    trace = websearch.trace_from_response(blocks)
    assert trace.errors == ["max_uses_exceeded"]
    assert trace.results == []


def test_trace_is_empty_when_no_search_happened():
    trace = websearch.trace_from_response([{"type": "text", "text": "A TFN is ..."}])
    assert trace.used is False


def test_trace_tolerates_empty_response():
    assert websearch.trace_from_response([]).used is False
    assert websearch.trace_from_response(None).used is False


# ── Merge: live results still get re-checked ─────────────────────────────

def test_untrusted_search_result_is_dropped_on_merge():
    """Defence in depth: even if a result slipped past the API restriction."""
    trace = websearch.SearchTrace(results=[
        {"url": "https://www.ato.gov.au/tfn", "title": "TFN", "domain": "ato.gov.au"},
        {"url": "https://dodgy-visa-help.com/x", "title": "?", "domain": "dodgy-visa-help.com"},
    ])
    merged = websearch.merge_sources([], trace)
    domains = {m["domain"] for m in merged}
    assert "ato.gov.au" in domains
    assert "dodgy-visa-help.com" not in domains
