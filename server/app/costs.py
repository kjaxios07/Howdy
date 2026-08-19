"""What one answer costs.

Two jobs:

1. `price()` turns a real API usage object into dollars. It is what the app
   calls after every answer, so the number in the report is measured, not
   guessed.
2. `estimate()` predicts the same number from prompt sizes, so we can reason
   about pricing before there is traffic.

Pure module — no database, no HTTP, no SDK. That keeps it unit-testable and
means the price table can be checked without standing anything up.

Prices verified 2026-08-19 against
https://platform.claude.com/docs/en/about-claude/pricing
Re-check that page when the model changes. `PRICES_VERIFIED` below is the
date, and `test_costs.py` fails if it goes stale by more than 180 days —
a wrong price table is worse than no price table.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date

PRICES_VERIFIED = date(2026, 8, 19)

# Dollars per million tokens.
#
# Note on Sonnet 5: the $2/$10 launch price was announced as introductory
# through 2026-08-31. It is now the standard price and the increase to
# $3/$15 will NOT happen. Anything in our notes assuming a September rise
# is out of date.
PRICES: dict[str, dict[str, float]] = {
    "claude-sonnet-5": {"input": 2.00, "cache_write_5m": 2.50, "cache_read": 0.20, "output": 10.00},
    "claude-haiku-4-5": {"input": 1.00, "cache_write_5m": 1.25, "cache_read": 0.10, "output": 5.00},
    "claude-opus-5":   {"input": 5.00, "cache_write_5m": 6.25, "cache_read": 0.50, "output": 25.00},
}

# Server-side tools are billed on top of tokens.
WEB_SEARCH_PER_SEARCH = 10.00 / 1000   # $10 per 1,000 searches
WEB_FETCH_PER_FETCH = 0.0              # no additional charge

# Declaring any tool adds a tool-use system prompt. Sonnet 5, tool_choice auto.
TOOL_SYSTEM_TOKENS = {"claude-sonnet-5": 354, "claude-haiku-4-5": 496, "claude-opus-5": 286}

# The docs' own rule of thumb. Only used by estimate(); price() uses real counts.
CHARS_PER_TOKEN = 4.0


@dataclass(frozen=True)
class Usage:
    """The fields we care about from an API usage object."""

    input_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0
    output_tokens: int = 0
    web_searches: int = 0

    @classmethod
    def from_api(cls, usage) -> "Usage":
        """Map an SDK usage object (or dict) onto this shape.

        Tolerant on purpose: the SDK grows fields, and a missing one should
        under-report by a rounding error rather than crash an answer.
        """
        get = usage.get if isinstance(usage, dict) else lambda k, d=0: getattr(usage, k, d)
        server = get("server_tool_use", None) or {}
        sget = server.get if isinstance(server, dict) else lambda k, d=0: getattr(server, k, d)
        return cls(
            input_tokens=int(get("input_tokens", 0) or 0),
            cache_creation_input_tokens=int(get("cache_creation_input_tokens", 0) or 0),
            cache_read_input_tokens=int(get("cache_read_input_tokens", 0) or 0),
            output_tokens=int(get("output_tokens", 0) or 0),
            web_searches=int(sget("web_search_requests", 0) or 0),
        )


@dataclass(frozen=True)
class Cost:
    """One answer, itemised. Dollars."""

    input: float = 0.0
    cache_write: float = 0.0
    cache_read: float = 0.0
    output: float = 0.0
    search: float = 0.0

    @property
    def total(self) -> float:
        return self.input + self.cache_write + self.cache_read + self.output + self.search

    @property
    def cents(self) -> float:
        return self.total * 100

    def as_dict(self) -> dict:
        d = {k: round(v, 8) for k, v in self.__dict__.items()}
        d["total"] = round(self.total, 8)
        return d

    def __str__(self) -> str:
        return f"{self.cents:.3f}c"


def price(model: str, usage: Usage) -> Cost:
    """Real cost of one answer from its real usage."""
    p = PRICES.get(model)
    if p is None:
        raise KeyError(
            f"No price for {model!r}. Add it to PRICES from the pricing page — "
            "do not let an unpriced model bill silently."
        )
    m = 1_000_000
    return Cost(
        input=usage.input_tokens * p["input"] / m,
        cache_write=usage.cache_creation_input_tokens * p["cache_write_5m"] / m,
        cache_read=usage.cache_read_input_tokens * p["cache_read"] / m,
        output=usage.output_tokens * p["output"] / m,
        search=usage.web_searches * WEB_SEARCH_PER_SEARCH,
    )


# ── Estimation, for planning before there is traffic ─────────────────────

@dataclass
class Shape:
    """The shape of a typical request, in tokens."""

    cached_prefix: int          # system prompt + tool definitions — stable, cacheable
    fresh_input: int            # history + this question — changes every time
    output: int
    searches: int = 0
    search_result_tokens: int = 0   # what the search puts back into context
    cache_hit: bool = True


def estimate(model: str, shape: Shape) -> Cost:
    """Predicted cost of one answer of this shape."""
    usage = Usage(
        input_tokens=shape.fresh_input + shape.search_result_tokens,
        cache_creation_input_tokens=0 if shape.cache_hit else shape.cached_prefix,
        cache_read_input_tokens=shape.cached_prefix if shape.cache_hit else 0,
        output_tokens=shape.output,
        web_searches=shape.searches,
    )
    return price(model, usage)


def tokens_of(text: str) -> int:
    """Rough token count from characters.

    Only for estimation. The real number comes from usage on a live call, or
    from client.messages.count_tokens() if you want it before sending.
    """
    return int(len(text) / CHARS_PER_TOKEN)


def measured_shape(model: str = "claude-sonnet-5") -> dict:
    """Measure this app's actual prompt, so the estimate uses our numbers."""
    from .appconfig import limits, trusted_domains
    from .prompt import system_prompt

    sp = system_prompt()
    domains = sorted(trusted_domains())
    # The allowlist ships inside the web_search tool definition, so it is real
    # input tokens on every request that declares the tool.
    tool_def = json.dumps({"allowed_domains": domains})
    lim = limits()

    return {
        "system_prompt_chars": len(sp),
        "system_prompt_tokens": tokens_of(sp),
        "tool_def_tokens": tokens_of(tool_def) + TOOL_SYSTEM_TOKENS.get(model, 400),
        "max_history_tokens": tokens_of("x" * int(lim["max_history_chars"])),
        "max_question_tokens": tokens_of("x" * int(lim["max_message_chars"])),
        "max_output_tokens": 700,
        "trusted_domains": len(domains),
    }


# ── CLI ──────────────────────────────────────────────────────────────────

def _bar(label: str, cost: Cost, worst: float, width: int = 34) -> str:
    n = max(1, round(cost.total / worst * width)) if worst else 1
    return f"  {label:<34} {'█' * n:<{width}}  {cost.cents:>7.3f}c"


def _estimate_report(model: str = "claude-sonnet-5") -> None:
    m = measured_shape(model)
    prefix = m["system_prompt_tokens"] + m["tool_def_tokens"]
    typical_q = tokens_of("How many hours can I work on a student visa?")
    typical_hist = m["max_history_tokens"] // 2

    print(f"\n  MEASURED FROM THIS REPO — model {model}")
    print(f"  system prompt            {m['system_prompt_chars']:>7,} chars  ~{m['system_prompt_tokens']:>6,} tokens")
    print(f"  web_search tool def      {m['trusted_domains']:>7,} domains ~{m['tool_def_tokens']:>6,} tokens")
    print(f"  cacheable prefix                          ~{prefix:>6,} tokens")
    print(f"  history cap / question cap                 {m['max_history_tokens']:>6,} / {m['max_question_tokens']:,} tokens")
    print(f"  output cap                                 {m['max_output_tokens']:>6,} tokens\n")

    cases = {
        "Knowledge-base answer (cached)":
            Shape(prefix, typical_hist + typical_q, 270),
        "Knowledge-base answer (cache miss)":
            Shape(prefix, typical_hist + typical_q, 270, cache_hit=False),
        "One live search":
            Shape(prefix, typical_hist + typical_q, 480, searches=1, search_result_tokens=2000),
        "Three live searches (our cap)":
            Shape(prefix, typical_hist + typical_q, 700, searches=3, search_result_tokens=6000),
        "Worst case: miss + 3 searches":
            Shape(prefix, m["max_history_tokens"] + m["max_question_tokens"], 700,
                  searches=3, search_result_tokens=6000, cache_hit=False),
    }
    costs = {k: estimate(model, s) for k, s in cases.items()}
    worst = max(c.total for c in costs.values())

    print("  COST PER ANSWER")
    for label, c in costs.items():
        print(_bar(label, c, worst))

    c = costs["One live search"]
    print(f"\n  Of a searched answer, the search fee alone is "
          f"{c.search / c.total * 100:.0f}% ({c.search * 100:.1f}c of {c.cents:.2f}c).")

    print("\n  WHAT A USER COSTS PER MONTH")
    kb, srch = costs["Knowledge-base answer (cached)"], costs["One live search"]
    for qs in (10, 30, 60, 120):
        for mix, name in ((0.2, "20% searched"), (0.5, "50% searched")):
            cost = qs * (kb.total * (1 - mix) + srch.total * mix)
            print(f"  {qs:>4} questions/month, {name:<13} ${cost:>6.3f}")

    print("\n  BREAK-EVEN ON THE $5 STUDENT DEALS TIER")
    for mix, name in ((0.5, "50% searched"), (1.0, "every answer searched")):
        per = kb.total * (1 - mix) + srch.total * mix
        print(f"  {name:<22} {5.0 / per:>7,.0f} answers/month before it loses money")

    print(f"\n  Prices verified {PRICES_VERIFIED}. Token counts are estimated at "
          f"{CHARS_PER_TOKEN} chars/token;\n  once the app is live, `costs report` uses real usage instead.\n")


def main(argv: list[str] | None = None) -> int:
    import sys

    args = list(argv if argv is not None else sys.argv[1:])
    cmd = args[0] if args else "estimate"
    model = args[1] if len(args) > 1 else "claude-sonnet-5"

    if cmd == "estimate":
        _estimate_report(model)
        return 0
    if cmd == "report":
        from .costreport import print_report

        print_report()
        return 0
    print("usage: python -m app.costs [estimate|report] [model]")
    return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
