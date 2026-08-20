"""Tests for the spend ceiling.

The point of this module is not accounting — it is that a good week cannot
produce a bill nobody agreed to. So most of these tests are about the two
invariants that make the ceiling safe to leave switched on:

    a safety question is never degraded, at any stage, including past the cap
    paying users degrade one stage later than free ones

and the third, which is about the ceiling not becoming a fragility:

    a Redis fault reports NORMAL, never a false lockout
"""

from __future__ import annotations

import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import budget as b  # noqa: E402


class FakeRedis:
    def __init__(self):
        self.kv: dict[str, int] = {}

    async def mget(self, *keys):
        return [self.kv.get(k) for k in keys]

    def pipeline(self, transaction=True):
        return FakePipe(self)


class FakePipe:
    def __init__(self, r):
        self.r, self.ops = r, []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def incrby(self, k, n):
        self.ops.append(("incrby", k, n))

    def expire(self, k, ttl):
        self.ops.append(("expire", k, ttl))

    async def execute(self):
        for op in self.ops:
            if op[0] == "incrby":
                self.r.kv[op[1]] = self.r.kv.get(op[1], 0) + op[2]
        self.ops.clear()


@pytest.fixture(autouse=True)
def fake(monkeypatch):
    r = FakeRedis()
    monkeypatch.setattr(b, "redis_client", lambda: r)
    return r


def run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


def spend(fake, usd: float) -> None:
    run(b.add(round(usd * 1_000_000)))


# ── The ladder ───────────────────────────────────────────────────────────

def test_a_quiet_day_is_normal(fake):
    assert run(b.state()).mode == b.NORMAL


def test_the_ladder_climbs_in_order(fake):
    """Each stage removes one more expensive thing, and only when the previous
    stage was not enough. Switching straight from working to off is the
    behaviour this whole module exists to avoid."""
    cap = b.daily_cap()
    seen = []
    for fraction in (0.10, 0.65, 0.90, 1.05):
        fake.kv.clear()
        spend(fake, cap * fraction)
        seen.append(run(b.state()).mode)
    assert seen == [b.NORMAL, b.NO_SEARCH, b.CACHE_ONLY, b.PAUSED]


def test_the_tighter_cap_wins(fake):
    """Daily and monthly caps are both live. Being under the month's ceiling is
    no comfort if today already spent a fortnight's worth."""
    day, month = b._keys()
    fake.kv[day] = round(b.daily_cap() * 0.95 * 1_000_000)
    fake.kv[month] = round(b.monthly_cap() * 0.01 * 1_000_000)
    assert run(b.state()).mode == b.CACHE_ONLY


def test_spend_accumulates_across_answers(fake):
    for _ in range(4):
        spend(fake, b.daily_cap() / 4)
    assert run(b.state()).spent_today == pytest.approx(b.daily_cap(), rel=1e-6)


def test_the_two_counters_are_separate(fake):
    spend(fake, 1.0)
    day, month = b._keys()
    assert fake.kv[day] == fake.kv[month] == 1_000_000
    assert day != month


# ── Safety is never degraded ─────────────────────────────────────────────

def test_a_safety_question_is_answered_fully_past_the_cap(fake):
    """The ceiling protects against a surprise bill, not against helping
    someone in danger. If honouring that overshoots, we overshoot."""
    spend(fake, b.daily_cap() * 3)
    state = run(b.state())
    assert state.mode == b.PAUSED
    for tier in ("guest", "free", "deals"):
        assert b.effective_mode(state, tier=tier, exempt=True) == b.NORMAL


def test_safety_keeps_live_search_at_every_stage(fake):
    for fraction in (0.65, 0.90, 1.05, 10.0):
        fake.kv.clear()
        spend(fake, b.daily_cap() * fraction)
        state = run(b.state())
        assert b.effective_mode(state, tier="guest", exempt=True) == b.NORMAL, fraction


# ── Paying users degrade later ───────────────────────────────────────────

def test_paying_users_are_one_stage_behind(fake):
    pairs = [
        (0.65, b.NO_SEARCH, b.NORMAL),
        (0.90, b.CACHE_ONLY, b.NO_SEARCH),
        (1.05, b.PAUSED, b.CACHE_ONLY),
    ]
    for fraction, free_mode, paid_mode in pairs:
        fake.kv.clear()
        spend(fake, b.daily_cap() * fraction)
        state = run(b.state())
        assert b.effective_mode(state, tier="free", exempt=False) == free_mode, fraction
        assert b.effective_mode(state, tier="deals", exempt=False) == paid_mode, fraction


def test_a_paying_user_is_never_paused_by_the_daily_cap(fake):
    """They gave us money today. Being told to come back tomorrow is the one
    outcome that should cost us the subscription."""
    spend(fake, b.daily_cap() * 5)
    state = run(b.state())
    assert b.effective_mode(state, tier="deals", exempt=False) != b.PAUSED


def test_guests_and_free_users_degrade_together(fake):
    """Signing in is not a paid tier. The distinction that buys leniency is
    paying, not having an account."""
    spend(fake, b.daily_cap() * 0.90)
    state = run(b.state())
    assert b.effective_mode(state, tier="guest", exempt=False) == b.effective_mode(
        state, tier="free", exempt=False
    )


# ── Failure behaviour ────────────────────────────────────────────────────

def test_a_broken_counter_reports_normal_not_paused(monkeypatch):
    """Failing open is deliberate. A Redis blip must not read as "we are out of
    money" and take the product down — the durable answer_costs rows are still
    there to reconcile against."""
    class Broken:
        async def mget(self, *k):
            raise RuntimeError("redis down")

    monkeypatch.setattr(b, "redis_client", lambda: Broken())
    assert run(b.state()).mode == b.NORMAL


def test_recording_spend_never_raises(monkeypatch):
    class Broken:
        def pipeline(self, transaction=True):
            raise RuntimeError("redis down")

    monkeypatch.setattr(b, "redis_client", lambda: Broken())
    run(b.add(1_000_000))  # must not raise


def test_turning_the_guard_off_disables_it(fake, monkeypatch):
    spend(fake, b.daily_cap() * 5)
    monkeypatch.setattr(b, "enabled", lambda: False)
    assert run(b.state()).mode == b.NORMAL


def test_no_caps_configured_means_no_ceiling(monkeypatch, fake):
    monkeypatch.setattr(b, "daily_cap", lambda: 0.0)
    monkeypatch.setattr(b, "monthly_cap", lambda: 0.0)
    assert run(b.state()).mode == b.NORMAL


def test_zero_and_negative_spend_are_ignored(fake):
    run(b.add(0))
    run(b.add(-5))
    assert fake.kv == {}


# ── What the student reads ───────────────────────────────────────────────

def test_the_message_never_mentions_money():
    """Our cost problem is not the student's problem. They should read a
    capacity note, not a budget statement."""
    for mode in (b.CACHE_ONLY, b.PAUSED):
        text = b.message(mode).lower()
        for word in ("budget", "cost", "spend", "bill", "$", "afford", "credit", "quota"):
            assert word not in text, (mode, word)


def test_the_paused_message_still_points_somewhere(fake):
    """A dead end is the one thing a companion must never be. Even switched
    off, the crisis numbers are on the screen."""
    text = b.message(b.PAUSED)
    assert "000" in text and "13 11 14" in text


def test_normal_has_nothing_to_say():
    assert b.message(b.NORMAL) == ""


def test_the_lean_message_says_safety_still_works():
    for mode in (b.CACHE_ONLY, b.PAUSED):
        assert "safety" in b.message(mode).lower(), mode


# ── Shape ────────────────────────────────────────────────────────────────

def test_status_is_reportable(fake):
    spend(fake, b.daily_cap() * 0.5)
    s = run(b.status())
    assert s["mode"] == b.NORMAL
    assert s["spent_today_usd"] == pytest.approx(b.daily_cap() * 0.5)
    assert 0 < s["used_fraction"] < 1
    assert s["remaining_month_usd"] > 0


def test_the_public_endpoint_does_not_publish_our_spend():
    """/api/budget tells a client the product is running lean so the UI can
    soften. It must not report how close to the cap we are — that would tell
    anyone who wants to push us over it exactly how far they have to go."""
    import ast
    import pathlib

    src = (pathlib.Path(__file__).parent.parent / "app" / "main.py").read_text()
    fn = next(
        n for n in ast.walk(ast.parse(src))
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "budget_status"
    )
    # The docstring explains what is withheld and names those fields, so it is
    # dropped before the check — otherwise the explanation trips the test.
    statements = [n for n in fn.body if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant))]
    body = "".join(ast.dump(n) for n in statements)
    for leak in ("spent_today", "spent_month", "used_fraction", "remaining", "cap", "'status'"):
        assert leak not in body, leak


def test_spend_is_not_a_database_table():
    """Same stance as the quota counters and the answer cache: a rolling
    number in Redis, not a durable record. `answer_costs` already holds the
    part worth keeping, and it carries no identity."""
    from app import models

    tables = {v.__tablename__ for v in vars(models).values() if hasattr(v, "__tablename__")}
    assert not any("budget" in t or "spend" in t for t in tables), tables


def test_the_configured_caps_are_real_numbers():
    """A cap of zero would silently mean "no ceiling", which is the opposite of
    what this config block is for."""
    assert b.enabled()
    assert b.monthly_cap() > 0
    assert b.daily_cap() > 0
    assert b.daily_cap() < b.monthly_cap()


def test_no_search_actually_removes_the_search_tool():
    """The saving has to be structural, not a request. `no_search` means the
    tool is never attached, so the model cannot search even if it wants to.

    Checked against the source because chat.py needs the Anthropic SDK to
    import and this suite deliberately runs without it. If the gate is ever
    deleted the ladder's first and cheapest stage silently stops saving
    anything, which is exactly the kind of failure nobody notices.
    """
    import ast
    import pathlib

    src = (pathlib.Path(__file__).parent.parent / "app" / "routers" / "chat.py").read_text()
    fn = next(
        n for n in ast.walk(ast.parse(src))
        if isinstance(n, ast.FunctionDef) and n.name == "_request_kwargs"
    )
    body = ast.dump(fn)
    assert "tool_definition" in body
    assert "NORMAL" in body, "the search tool is attached unconditionally"

    # And both callers must pass the mode through, or the gate never closes.
    assert src.count("_request_kwargs(history, message, spend_mode)") == 2


def test_thresholds_are_ordered_and_within_the_cap():
    t = b.thresholds()
    assert 0 < t[b.NO_SEARCH] < t[b.CACHE_ONLY] < t[b.PAUSED]
    assert t[b.PAUSED] <= 1.0, "pausing after the cap defeats the point of a cap"
