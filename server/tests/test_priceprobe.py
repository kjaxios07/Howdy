"""Tests for the price probe.

Two things are being protected here. One is fairness: a student must see the
same price every time, or the probe is just deceiving people at random. The
other is honesty about statistics — the probe must refuse to hand over a
verdict it does not have the traffic to support, because a number that looks
like an answer will be acted on.
"""

from __future__ import annotations

import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import priceprobe as pp  # noqa: E402


class FakeRedis:
    def __init__(self):
        self.kv: dict[str, int] = {}

    async def incr(self, k):
        self.kv[k] = self.kv.get(k, 0) + 1

    async def get(self, k):
        return self.kv.get(k)

    async def set(self, k, v, ex=None, nx=False):
        if nx and k in self.kv:
            return None
        self.kv[k] = v
        return True


@pytest.fixture(autouse=True)
def fake(monkeypatch):
    r = FakeRedis()
    monkeypatch.setattr(pp, "redis_client", lambda: r)
    monkeypatch.setattr(pp, "enabled", lambda: True)
    return r


def run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


# ── One student, one price ───────────────────────────────────────────────

def test_the_same_student_always_sees_the_same_price():
    """Across visits, devices and logouts. Showing someone $5 on Monday and
    $10 on Friday is a fair thing to be angry about."""
    for subject in ("u-1", "u-2", "ip-abc", "9f2c"):
        seen = {pp.variant_for(subject) for _ in range(50)}
        assert len(seen) == 1, subject


def test_the_price_survives_a_restart():
    """Derived from a hash, not stored — so nothing is lost if Redis is."""
    before = pp.variant_for("u-1")
    fresh = pp.variant_for("u-1")
    assert before == fresh


def test_changing_the_salt_starts_a_clean_round(monkeypatch):
    first = [pp.variant_for(f"u-{i}") for i in range(200)]
    monkeypatch.setattr(pp, "salt", lambda: "kip-price-round-2")
    second = [pp.variant_for(f"u-{i}") for i in range(200)]
    assert first != second


def test_the_arms_are_roughly_even():
    """A hash split that quietly favoured one arm would bias every result the
    probe ever produced."""
    counts = {p: 0 for p in pp.prices()}
    for i in range(4000):
        counts[pp.variant_for(f"student-{i}")] += 1
    for price, n in counts.items():
        assert 0.45 < n / 4000 < 0.55, counts


def test_every_assigned_price_is_a_configured_one():
    assert {pp.variant_for(f"u-{i}") for i in range(500)} <= set(pp.prices())


def test_the_probe_off_means_one_price_for_everyone(monkeypatch):
    monkeypatch.setattr(pp, "enabled", lambda: False)
    assert {pp.variant_for(f"u-{i}") for i in range(100)} == {pp.prices()[0]}


# ── The offer ────────────────────────────────────────────────────────────

def test_the_offer_never_contains_a_trial():
    """A standing instruction, asserted rather than remembered."""
    for i in range(50):
        o = pp.offer(f"u-{i}")
        assert o["trial"] is None
        assert "trial" not in str(o.get("monthly")) and "trial" not in str(o.get("annual"))


def test_annual_is_cheaper_per_month_than_monthly():
    o = pp.offer("u-1")
    assert o["annual"] < o["monthly"] * 12
    assert o["currency"] == "AUD"


# ── Counting ─────────────────────────────────────────────────────────────

def test_shown_and_tapped_land_on_the_right_arm(fake):
    price = run(pp.shown("u-1"))
    assert run(pp.tapped("u-1")) == price
    assert fake.kv[pp._key(price, "shown")] == 1
    assert fake.kv[pp._key(price, "tapped")] == 1


def test_one_person_refreshing_is_still_one_impression(fake):
    """Otherwise the denominator inflates with engagement, and conversion
    looks worse the more someone cares. The unit of the experiment is a
    person, not a page load."""
    price = run(pp.shown("u-1"))
    for _ in range(9):
        run(pp.shown("u-1"))
    assert fake.kv[pp._key(price, "shown")] == 1


def test_different_people_are_counted_separately(fake):
    for i in range(40):
        run(pp.shown(f"u-{i}"))
    assert sum(fake.kv.get(pp._key(p, "shown"), 0) for p in pp.prices()) == 40


def test_the_seen_marker_cannot_be_read_back_to_a_person(fake):
    run(pp.shown("kaja@example.com"))
    joined = " ".join(fake.kv)
    assert "kaja" not in joined and "@" not in joined


def test_counting_never_breaks_the_paywall(monkeypatch):
    class Broken:
        async def set(self, *a, **k):
            raise RuntimeError("redis down")

        async def incr(self, k):
            raise RuntimeError("redis down")

    monkeypatch.setattr(pp, "redis_client", lambda: Broken())
    assert run(pp.shown("u-1")) in pp.prices()  # must not raise


def test_the_counters_hold_no_identity(fake):
    for i in range(20):
        run(pp.shown(f"student-{i}@example.com"))
    joined = " ".join(fake.kv)
    assert "@" not in joined and "student" not in joined


def test_the_probe_is_not_a_database_table():
    from app import models

    tables = {v.__tablename__ for v in vars(models).values() if hasattr(v, "__tablename__")}
    assert not any("probe" in t or "price" in t for t in tables), tables


# ── Refusing to answer too early ─────────────────────────────────────────

def test_a_thin_probe_reports_not_ready_rather_than_a_rate(fake):
    """Eleven impressions is not a conversion rate, and a number that looks
    like an answer will be acted on."""
    for i in range(11):
        run(pp.shown(f"u-{i}"))
    out = run(pp.read())
    assert out["ready"] is False
    assert "verdict" not in out
    assert "need" in out["reason"]


def test_an_empty_probe_does_not_divide_by_zero(fake):
    out = run(pp.read())
    assert out["ready"] is False
    assert out["impressions"] == 0


def test_a_broken_read_says_so_rather_than_guessing(monkeypatch):
    class Broken:
        async def get(self, k):
            raise RuntimeError("redis down")

    monkeypatch.setattr(pp, "redis_client", lambda: Broken())
    assert run(pp.read())["ready"] is False


# ── The statistics ───────────────────────────────────────────────────────

def test_smaller_differences_cost_more_traffic():
    """The whole argument for two far-apart arms rests on this shape."""
    big = pp.required_per_arm(0.03, 1.00)
    small = pp.required_per_arm(0.03, 0.20)
    assert small > big * 10


def test_rarer_conversion_costs_more_traffic():
    assert pp.required_per_arm(0.01, 0.50) > pp.required_per_arm(0.10, 0.50)


def test_the_configured_arms_are_resolvable_at_plausible_traffic():
    """If the arms as configured needed 40,000 impressions each, the probe
    would be theatre. Two far-apart prices at a 3% tap-through is a few
    thousand sessions — reachable."""
    assert len(pp.prices()) == 2, "a third arm roughly triples the traffic needed"
    assert max(pp.prices()) >= 2 * min(pp.prices()), "the arms must be far apart to resolve"
    assert pp.required_per_arm(0.03, 1.00) < 2000


# ── Reading it ───────────────────────────────────────────────────────────

def test_the_verdict_ranks_on_revenue_not_conversion(fake):
    """Half the conversion at twice the price is the same business, and a
    probe that ranked on conversion would always pick the cheapest arm."""
    low, high = min(pp.prices()), max(pp.prices())
    a = pp.Arm(low, shown=1000, tapped=40)      # 4.0%  -> 0.200/impression at $5
    b = pp.Arm(high, shown=1000, tapped=30)     # 3.0%  -> 0.300/impression at $10
    assert b.rate < a.rate
    assert b.revenue_per_impression > a.revenue_per_impression


def test_a_gap_inside_the_noise_is_reported_as_a_tie(fake):
    for price in pp.prices():
        fake.kv[pp._key(price, "shown")] = 5000
        fake.kv[pp._key(price, "tapped")] = 150
    fake.kv[pp._key(pp.prices()[0], "tapped")] = 152  # a two-tap difference
    out = run(pp.read())
    assert out["ready"] is True
    assert out["significant"] is False
    assert "tied" in out["verdict"]


def test_a_real_difference_is_called(fake):
    low, high = min(pp.prices()), max(pp.prices())
    fake.kv[pp._key(low, "shown")] = 5000
    fake.kv[pp._key(low, "tapped")] = 150       # 3.0%
    fake.kv[pp._key(high, "shown")] = 5000
    fake.kv[pp._key(high, "tapped")] = 250      # 5.0%, and twice the money
    out = run(pp.read())
    assert out["ready"] is True
    assert out["leader"] == high
    assert out["significant"] is True


def test_an_arm_with_no_traffic_cannot_win(fake):
    for price in pp.prices():
        fake.kv[pp._key(price, "shown")] = 5000
        fake.kv[pp._key(price, "tapped")] = 150
    fake.kv[pp._key(pp.prices()[1], "shown")] = 0
    fake.kv[pp._key(pp.prices()[1], "tapped")] = 0
    out = run(pp.read())
    assert out["ready"] is False
