"""Tests for cost accounting.

A wrong price table is worse than no price table — it produces confident
numbers that a pricing decision gets made on. These check the arithmetic,
the staleness of the table, and the two mistakes that would quietly
under-report: dropping resumed legs of a turn, and forgetting that a search
is billed on top of tokens.
"""

from __future__ import annotations

import os
import sys
from datetime import date, timedelta

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import costs  # noqa: E402
from app.costs import PRICES, Shape, Usage, estimate, price  # noqa: E402


# ── The price table ──────────────────────────────────────────────────────

def test_price_table_is_not_stale():
    """Prices move. A table nobody has re-checked in six months should fail
    the build rather than keep answering pricing questions."""
    age = date.today() - costs.PRICES_VERIFIED
    assert age < timedelta(days=180), (
        f"PRICES last verified {age.days} days ago. Re-check "
        "https://platform.claude.com/docs/en/about-claude/pricing and bump PRICES_VERIFIED."
    )


def test_cache_multipliers_match_the_published_ratios():
    """Cache write is 1.25x input and a read is 0.1x. If a price is ever
    edited by hand, this catches a typo in one field."""
    for model, p in PRICES.items():
        assert p["cache_write_5m"] == pytest.approx(p["input"] * 1.25), model
        assert p["cache_read"] == pytest.approx(p["input"] * 0.10), model


def test_output_costs_five_times_input():
    for model, p in PRICES.items():
        assert p["output"] == pytest.approx(p["input"] * 5), model


def test_unpriced_model_raises_rather_than_billing_silently():
    with pytest.raises(KeyError, match="No price"):
        price("claude-imaginary-9", Usage(input_tokens=100))


def test_web_search_is_a_cent_per_search():
    assert costs.WEB_SEARCH_PER_SEARCH == pytest.approx(0.01)


def test_web_fetch_is_free():
    assert costs.WEB_FETCH_PER_FETCH == 0.0


# ── The arithmetic ───────────────────────────────────────────────────────

def test_known_usage_prices_correctly():
    """Hand-computed against Sonnet 5: $2 in / $0.20 cache read / $10 out."""
    c = price("claude-sonnet-5", Usage(
        input_tokens=1000,            # 1000 * 2/1e6      = 0.002
        cache_read_input_tokens=10_000,  # 10000 * 0.2/1e6 = 0.002
        output_tokens=500,            # 500 * 10/1e6      = 0.005
    ))
    assert c.input == pytest.approx(0.002)
    assert c.cache_read == pytest.approx(0.002)
    assert c.output == pytest.approx(0.005)
    assert c.total == pytest.approx(0.009)
    assert c.cents == pytest.approx(0.9)


def test_searches_are_billed_on_top_of_tokens():
    """The failure mode this catches: counting only tokens and concluding
    search is cheap. At our volumes the fee is about half a searched answer."""
    no_search = price("claude-sonnet-5", Usage(input_tokens=1000, output_tokens=500))
    with_search = price("claude-sonnet-5", Usage(input_tokens=1000, output_tokens=500, web_searches=1))
    assert with_search.total - no_search.total == pytest.approx(0.01)


def test_cache_read_is_ten_times_cheaper_than_fresh_input():
    fresh = price("claude-sonnet-5", Usage(input_tokens=10_000))
    cached = price("claude-sonnet-5", Usage(cache_read_input_tokens=10_000))
    assert fresh.total == pytest.approx(cached.total * 10)


# ── Reading usage off the API response ───────────────────────────────────

def test_usage_reads_a_dict():
    u = Usage.from_api({
        "input_tokens": 105, "output_tokens": 6039,
        "cache_read_input_tokens": 7123, "cache_creation_input_tokens": 7345,
        "server_tool_use": {"web_search_requests": 2},
    })
    assert (u.input_tokens, u.output_tokens) == (105, 6039)
    assert (u.cache_read_input_tokens, u.cache_creation_input_tokens) == (7123, 7345)
    assert u.web_searches == 2


def test_usage_reads_an_object():
    class Server:
        web_search_requests = 1

    class U:
        input_tokens = 10
        output_tokens = 20
        cache_read_input_tokens = 30
        cache_creation_input_tokens = 40
        server_tool_use = Server()

    u = Usage.from_api(U())
    assert (u.input_tokens, u.output_tokens, u.web_searches) == (10, 20, 1)


def test_missing_fields_do_not_crash_an_answer():
    """Metering must degrade, never raise — a new SDK field should cost us
    accuracy, not somebody's answer."""
    u = Usage.from_api({"input_tokens": 5})
    assert u.input_tokens == 5
    assert u.web_searches == 0
    assert price("claude-sonnet-5", u).total > 0


def test_none_server_tool_use_is_handled():
    assert Usage.from_api({"input_tokens": 1, "server_tool_use": None}).web_searches == 0


# ── Multi-leg turns ──────────────────────────────────────────────────────

def test_resumed_turns_are_summed():
    """A search turn can pause and resume, so one answer is several API calls.
    Metering only the last leg under-reports the priciest answers."""
    from app.costreport import combine

    total = combine([
        Usage(input_tokens=100, output_tokens=50, web_searches=1),
        Usage(input_tokens=200, output_tokens=80, web_searches=2),
    ])
    assert total.input_tokens == 300
    assert total.output_tokens == 130
    assert total.web_searches == 3


def test_combine_of_nothing_is_zero():
    from app.costreport import combine

    assert combine([]).input_tokens == 0


# ── Estimation against the real prompt ───────────────────────────────────

def test_measured_shape_reflects_this_repo():
    m = costs.measured_shape()
    assert m["system_prompt_chars"] > 10_000, "the system prompt carries the knowledge base"
    assert m["trusted_domains"] >= 50
    assert m["max_output_tokens"] == 700


def test_a_cached_answer_costs_under_a_cent():
    """If this ever fails, the free tier's economics have changed and the
    pricing page needs revisiting before anything else."""
    m = costs.measured_shape()
    prefix = m["system_prompt_tokens"] + m["tool_def_tokens"]
    c = estimate("claude-sonnet-5", Shape(prefix, 400, 270))
    assert c.cents < 1.0, f"cached answer now {c.cents:.3f}c"


def test_a_cache_miss_costs_several_times_a_hit():
    m = costs.measured_shape()
    prefix = m["system_prompt_tokens"] + m["tool_def_tokens"]
    hit = estimate("claude-sonnet-5", Shape(prefix, 400, 270))
    miss = estimate("claude-sonnet-5", Shape(prefix, 400, 270, cache_hit=False))
    assert miss.total > hit.total * 3, "caching should be the dominant saving"


def test_haiku_is_cheaper_than_sonnet_for_the_same_shape():
    """The cheap-model question should be answerable from the table, not a guess."""
    m = costs.measured_shape()
    prefix = m["system_prompt_tokens"] + m["tool_def_tokens"]
    shape = Shape(prefix, 400, 270)
    assert estimate("claude-haiku-4-5", shape).total < estimate("claude-sonnet-5", shape).total


def test_search_fee_dominates_a_searched_answer():
    """Documents the finding that drives the $5 tier: the per-search fee is
    the biggest single line in a searched answer, not the tokens."""
    m = costs.measured_shape()
    prefix = m["system_prompt_tokens"] + m["tool_def_tokens"]
    c = estimate("claude-sonnet-5", Shape(prefix, 400, 480, searches=1, search_result_tokens=2000))
    assert c.search > c.output
    assert c.search / c.total > 0.35


# ── The meter carries no identity ────────────────────────────────────────

def test_cost_rows_cannot_be_traced_to_a_person():
    from app.models import AnswerCost

    columns = {c.name for c in AnswerCost.__table__.columns}
    forbidden = {"user_id", "session_id", "ip", "ip_hash", "email", "google_sub", "conversation_id"}
    assert not (columns & forbidden), f"identity column on answer_costs: {columns & forbidden}"


def test_cost_day_is_a_date_not_a_timestamp():
    """Same control as question_gaps: a timestamp would let a cost row be
    lined up against a login."""
    from sqlalchemy import Date

    from app.models import AnswerCost

    assert isinstance(AnswerCost.__table__.columns["day"].type, Date)


def test_money_is_stored_as_integer_micros():
    from sqlalchemy import Integer

    from app.models import AnswerCost

    assert isinstance(AnswerCost.__table__.columns["micro_usd"].type, Integer)
