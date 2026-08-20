"""What this costs and what breaks, at N users.

Built because "it's fine for testing but what about 500,000 students" deserves
arithmetic rather than reassurance. Every input is a named assumption you can
argue with, and the model prints them so nobody mistakes a projection for a
measurement.

    python -m app.scale                 the ladder, 1k → 500k
    python -m app.scale 500000          one size in detail
    python -m app.scale 500000 --levers what each fix is worth

Cost inputs come from app.costs, which is priced from the published rates and
this repo's real prompt. Usage inputs are estimates and marked as such.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from .costs import PRICES, Shape, estimate, measured_shape

# ── Assumptions. Argue with these, not with the arithmetic. ──────────────

@dataclass
class Assumptions:
    questions_per_user_month: float = 30      # a real free user; ~1/day
    searched_share: float = 0.20              # fraction needing a live check
    monthly_active_share: float = 0.55        # of registered users, in any month
    peak_multiple: float = 8.0                # peak/mean request rate (evenings, Feb/Jul)
    seconds_per_answer: float = 6.0           # connection held open while streaming
    paid_conversion: float = 0.02             # free → $5 Student Deals
    paid_price: float = 5.00
    uni_seat_price_year: float = 4.00         # per enrolled international student
    uni_coverage: float = 0.0                 # share of users covered by an institution deal

    # Levers — all default OFF so the base case is today's system.
    answer_cache_hit: float = 0.0             # share served from a stored answer
    cheap_model_share: float = 0.0            # share routed to Haiku
    model: str = "claude-sonnet-5"
    cheap_model: str = "claude-haiku-4-5"


def _per_answer(model: str, searched: bool) -> float:
    m = measured_shape(model)
    prefix = m["system_prompt_tokens"] + m["tool_def_tokens"]
    if searched:
        return estimate(model, Shape(prefix, 400, 480, searches=1, search_result_tokens=2000)).total
    return estimate(model, Shape(prefix, 400, 270)).total


@dataclass
class Result:
    users: int
    answers_month: float
    billable_answers: float
    model_cost: float
    infra_cost: float
    total_cost: float
    revenue: float
    mean_rps: float
    peak_rps: float
    peak_concurrent: float
    app_servers: int
    storage_gb: float

    @property
    def margin(self) -> float:
        return self.revenue - self.total_cost

    @property
    def cost_per_user(self) -> float:
        return self.total_cost / self.users if self.users else 0.0


def model_at(users: int, a: Assumptions) -> Result:
    active = users * a.monthly_active_share
    answers = active * a.questions_per_user_month

    # A cached answer costs essentially nothing: a fingerprint lookup, no model.
    billable = answers * (1 - a.answer_cache_hit)

    searched = billable * a.searched_share
    plain = billable - searched

    def blend(searched_flag: bool) -> float:
        dear = _per_answer(a.model, searched_flag)
        cheap = _per_answer(a.cheap_model, searched_flag)
        return dear * (1 - a.cheap_model_share) + cheap * a.cheap_model_share

    model_cost = searched * blend(True) + plain * blend(False)

    # Infrastructure. Deliberately coarse — it is an order of magnitude, and at
    # every scale below it is dwarfed by the model bill.
    mean_rps = answers / (30 * 24 * 3600)
    peak_rps = mean_rps * a.peak_multiple
    peak_concurrent = peak_rps * a.seconds_per_answer
    app_servers = max(1, int(peak_concurrent / 400) + 1)      # ~400 in-flight per box
    storage_gb = users * 0.0004 + answers * 0.0000012 * 12    # accounts + a year of messages

    infra = (
        app_servers * 24                    # app boxes
        + (0 if users < 20_000 else 180)    # managed Postgres with a replica
        + (0 if users < 20_000 else 60)     # managed Redis
        + storage_gb * 0.10                 # block storage + offsite backup
        + (0 if users < 100_000 else 200)   # Cloudflare paid tier at that traffic
    )

    paid_rev = users * a.paid_conversion * a.paid_price
    uni_rev = users * a.uni_coverage * a.uni_seat_price_year / 12

    return Result(
        users=users,
        answers_month=answers,
        billable_answers=billable,
        model_cost=model_cost,
        infra_cost=infra,
        total_cost=model_cost + infra,
        revenue=paid_rev + uni_rev,
        mean_rps=mean_rps,
        peak_rps=peak_rps,
        peak_concurrent=peak_concurrent,
        app_servers=app_servers,
        storage_gb=storage_gb,
    )


# ── Reporting ────────────────────────────────────────────────────────────

def _money(v: float) -> str:
    if abs(v) >= 1_000_000:
        return f"${v/1_000_000:,.2f}M"
    if abs(v) >= 1_000:
        return f"${v/1_000:,.1f}k"
    return f"${v:,.0f}"


def ladder(a: Assumptions | None = None) -> None:
    a = a or Assumptions()
    print(f"\n  {'users':>9} {'answers/mo':>12} {'model':>10} {'infra':>9} "
          f"{'total':>10} {'revenue':>10} {'margin':>11} {'peak rps':>9} {'boxes':>6}")
    print("  " + "─" * 96)
    for n in (1_000, 10_000, 50_000, 100_000, 250_000, 500_000):
        r = model_at(n, a)
        print(f"  {n:>9,} {r.answers_month:>12,.0f} {_money(r.model_cost):>10} "
              f"{_money(r.infra_cost):>9} {_money(r.total_cost):>10} {_money(r.revenue):>10} "
              f"{_money(r.margin):>11} {r.peak_rps:>9.1f} {r.app_servers:>6}")


def detail(users: int, a: Assumptions | None = None) -> None:
    a = a or Assumptions()
    r = model_at(users, a)
    print(f"\n  AT {users:,} REGISTERED USERS")
    print(f"  monthly active            {users * a.monthly_active_share:>14,.0f}")
    print(f"  answers a month           {r.answers_month:>14,.0f}")
    if a.answer_cache_hit:
        print(f"  of which billable         {r.billable_answers:>14,.0f}"
              f"   ({(1-a.answer_cache_hit)*100:.0f}% — rest served from cache)")
    print(f"\n  model                     {_money(r.model_cost):>14}")
    print(f"  infrastructure            {_money(r.infra_cost):>14}")
    print(f"  TOTAL                     {_money(r.total_cost):>14}"
          f"   ({r.cost_per_user*100:.1f}c per registered user)")
    print(f"\n  revenue                   {_money(r.revenue):>14}")
    print(f"  margin                    {_money(r.margin):>14}"
          f"   {'⚠ LOSS' if r.margin < 0 else 'ok'}")
    print(f"\n  LOAD")
    print(f"  mean                      {r.mean_rps:>14.1f} req/s")
    print(f"  peak (x{a.peak_multiple:.0f})               {r.peak_rps:>14.1f} req/s")
    print(f"  concurrent at peak        {r.peak_concurrent:>14,.0f} open connections")
    print(f"  app servers needed        {r.app_servers:>14,}")
    print(f"  storage                   {r.storage_gb:>14,.0f} GB")


def levers(users: int = 500_000) -> None:
    base = Assumptions()
    b = model_at(users, base)
    print(f"\n  WHAT EACH LEVER IS WORTH AT {users:,} USERS")
    print(f"  {'lever':<44}{'total/mo':>12}{'saved':>12}{'vs base':>10}")
    print("  " + "─" * 78)
    print(f"  {'(base — today’s system)':<44}{_money(b.total_cost):>12}{'—':>12}{'—':>10}")

    options = [
        ("Answer cache, 50% of questions repeat", replace(base, answer_cache_hit=0.50)),
        ("Answer cache, 65% (realistic once seeded)", replace(base, answer_cache_hit=0.65)),
        ("Route 60% of answers to a cheaper model", replace(base, cheap_model_share=0.60)),
        ("Halve live searches (20% → 10%)", replace(base, searched_share=0.10)),
        ("Cache 65% + cheap model 60%", replace(base, answer_cache_hit=0.65, cheap_model_share=0.60)),
        ("All three together", replace(base, answer_cache_hit=0.65, cheap_model_share=0.60,
                                        searched_share=0.10)),
    ]
    for label, a in options:
        r = model_at(users, a)
        saved = b.total_cost - r.total_cost
        print(f"  {label:<44}{_money(r.total_cost):>12}{_money(saved):>12}"
              f"{saved / b.total_cost * 100:>9.0f}%")

    print(f"\n  WHO PAYS FOR IT")
    best = replace(base, answer_cache_hit=0.65, cheap_model_share=0.60, searched_share=0.10)
    for cov, label in ((0.0, "consumer only ($5 tier, 2% convert)"),
                       (0.25, "+ 25% of users on a university deal"),
                       (0.50, "+ 50% on a university deal"),
                       (0.75, "+ 75% on a university deal")):
        r = model_at(users, replace(best, uni_coverage=cov))
        flag = "⚠ LOSS" if r.margin < 0 else "ok"
        print(f"  {label:<44}{_money(r.revenue):>12}{_money(r.margin):>12}   {flag}")


def _assumption_note(a: Assumptions) -> None:
    print(f"\n  ASSUMPTIONS — change these in app/scale.py and rerun")
    print(f"  {a.questions_per_user_month:.0f} questions per active user per month, "
          f"{a.searched_share*100:.0f}% needing a live check")
    print(f"  {a.monthly_active_share*100:.0f}% of registered users active in a month")
    print(f"  peak {a.peak_multiple:.0f}x mean, {a.seconds_per_answer:.0f}s per answer held open")
    print(f"  {a.paid_conversion*100:.0f}% convert to the ${a.paid_price:.0f} tier; "
          f"university seats at ${a.uni_seat_price_year:.0f}/student/year")
    print(f"  cost per answer is measured, not assumed — see app/costs.py\n")


def main(argv: list[str] | None = None) -> int:
    import sys

    args = list(argv if argv is not None else sys.argv[1:])
    a = Assumptions()

    if "--levers" in args:
        args.remove("--levers")
        levers(int(args[0]) if args else 500_000)
        _assumption_note(a)
        return 0

    if args:
        detail(int(args[0]), a)
    else:
        ladder(a)
    _assumption_note(a)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
