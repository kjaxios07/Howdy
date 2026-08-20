"""Letting students set the price instead of us guessing it.

The question "would you pay $10 a month?" is worthless. People are kind to
someone who built something, and stated willingness to pay is roughly
uncorrelated with paying. The only signal worth acting on is somebody
reaching for their wallet when they think it is real.

So this is an **intent probe**, not a survey. Different students see the
paywall at a different price. We measure who taps through to checkout. We do
not charge anyone — the flow stops at the last screen with an honest "not
open yet, want to be told when it is?" and an email box. That email list is
the second output, and arguably the more valuable one.

Three things this module is careful about:

**One student, one price.** The variant is derived from a hash of the
subject, so the price is stable for them across visits and devices. Showing
someone $5 on Monday and $10 on Friday is how you lose them, and it would be
a fair thing to be angry about.

**It records no one.** Counters are per-variant integers in Redis: shown,
tapped. There is no row per person, no identity, no timestamp finer than the
day — the same stance as the coverage-gap log. You cannot reconstruct who
saw what, and that is on purpose.

**It knows when it cannot answer.** `read()` reports "not enough traffic yet"
rather than a conversion rate computed from eleven impressions. Reading a
result too early is worse than having no probe at all, because you will act
on it. The arithmetic for that is in `required_per_arm()`.

Read the outcome as **revenue per impression**, not as conversion rate. A
price that converts half as well at twice the money is the same business,
and the tie-break is then churn and support load, not the probe.
"""

from __future__ import annotations

import hashlib
import logging
import math
from dataclasses import dataclass
from datetime import date

from .appconfig import raw

log = logging.getLogger(__name__)


def redis_client():
    """Lazy, so this module stays importable and testable without redis."""
    from .ratelimit import redis_client as _client

    return _client()


def _cfg() -> dict:
    return raw().get("price_probe", {})


def enabled() -> bool:
    return bool(_cfg().get("enabled", False))


def prices() -> list[int]:
    """The arms, in dollars per month."""
    return [int(p) for p in _cfg().get("prices", [5, 10])]


def salt() -> str:
    return str(_cfg().get("salt", "kip-price-2026"))


def min_detectable_lift() -> float:
    """The conversion gap the probe is designed to see, as a fraction.

    Not an arbitrary knob — it follows from how far apart the arms are. With
    $5 against $10, revenue per impression ties exactly when the dearer arm
    converts at half the rate. So the decision boundary is a 50% difference,
    and there is no point sizing the test to resolve anything finer: a 10%
    conversion gap between those two prices does not change what you charge.
    """
    return float(_cfg().get("min_detectable_lift", 0.50))


def annual_multiple() -> float:
    """Months charged for a year. 8 means two months free, which is the
    convention students already recognise from every other subscription."""
    return float(_cfg().get("annual_multiple", 8))


# ── Assigning a price ────────────────────────────────────────────────────


def variant_for(subject: str) -> int:
    """Which price this person sees, forever.

    Deterministic from the subject so it survives a logout, a new device and
    a Redis flush. The salt is what lets us start a clean second round later
    without everyone keeping their old price.
    """
    if not enabled():
        return prices()[0]
    arms = prices()
    digest = hashlib.sha256(f"{salt()}|{subject}".encode()).digest()
    return arms[int.from_bytes(digest[:8], "big") % len(arms)]


def offer(subject: str) -> dict:
    """What the paywall should say for this person."""
    price = variant_for(subject)
    return {
        "monthly": price,
        "annual": round(price * annual_multiple()),
        "currency": "AUD",
        # No trial, anywhere, ever — the copy has nowhere to drift.
        "trial": None,
    }


# ── Counting ─────────────────────────────────────────────────────────────


def _key(price: int, event: str) -> str:
    return f"probe:{salt()}:{price}:{event}"


async def shown(subject: str) -> int:
    """The paywall was displayed. Returns the price shown. Never raises."""
    price = variant_for(subject)
    await _bump(price, "shown", subject)
    return price


async def tapped(subject: str) -> int:
    """They reached for their wallet. Never raises."""
    price = variant_for(subject)
    await _bump(price, "tapped", subject)
    return price


def _seen_key(subject: str, event: str) -> str:
    """A once-a-day marker, keyed by a hash of the subject.

    It is the same shape as the quota counters: a hashed subject with a 24h
    TTL, holding a single bit. It cannot be read back into who anyone is, and
    it evaporates with the window.
    """
    who = hashlib.sha256(f"{salt()}|seen|{subject}".encode()).hexdigest()[:24]
    return f"probe:seen:{event}:{who}:{date.today().isoformat()}"


async def _bump(price: int, event: str, subject: str) -> None:
    """Count one person once a day, not one page load.

    Without this a student who refreshes twice is three impressions and the
    denominator quietly inflates — which makes conversion look worse the more
    engaged someone is. The unit of the experiment is a person, so that is
    what gets counted.
    """
    if not enabled():
        return
    try:
        r = redis_client()
        first = await r.set(_seen_key(subject, event), "1", ex=86400, nx=True)
        if not first:
            return
        await r.incr(_key(price, event))
        # A day counter too, so a probe can be read as a trend rather than one
        # number that quietly averages a good week with a bad one.
        await r.incr(f"{_key(price, event)}:{date.today().isoformat()}")
    except Exception:  # noqa: BLE001 — a probe must never break a paywall
        log.warning("price_probe_failed", exc_info=True)


# ── Reading it ───────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Arm:
    price: int
    shown: int
    tapped: int

    @property
    def rate(self) -> float:
        return self.tapped / self.shown if self.shown else 0.0

    @property
    def revenue_per_impression(self) -> float:
        """The number that actually decides it. A price converting half as
        well at twice the money is the same business."""
        return self.rate * self.price


def required_per_arm(baseline: float, lift: float, *, power: float = 0.80) -> int:
    """Impressions needed per arm to detect `lift` (relative) at 95%/80%.

    Standard two-proportion sample size. It is here so the probe can say "come
    back in three weeks" instead of handing over a number that looks like an
    answer. The uncomfortable output of this function is the point: a small
    difference between two prices is not measurable at the traffic a new
    product has, so do not design a test that depends on measuring one.
    """
    p1 = max(1e-6, min(1 - 1e-6, baseline))
    p2 = max(1e-6, min(1 - 1e-6, baseline * (1 + lift)))
    z_a, z_b = 1.96, 0.84 if power <= 0.80 else 1.28
    pbar = (p1 + p2) / 2
    num = (z_a * math.sqrt(2 * pbar * (1 - pbar)) + z_b * math.sqrt(p1 * (1 - p1) + p2 * (1 - p2))) ** 2
    return math.ceil(num / (p2 - p1) ** 2)


def _z(a: Arm, b: Arm) -> float:
    """Two-proportion z. Zero when there is nothing to compare."""
    if not a.shown or not b.shown:
        return 0.0
    pooled = (a.tapped + b.tapped) / (a.shown + b.shown)
    se = math.sqrt(pooled * (1 - pooled) * (1 / a.shown + 1 / b.shown))
    return (a.rate - b.rate) / se if se else 0.0


async def read() -> dict:
    """Where the probe stands, and whether it may be acted on yet."""
    arms: list[Arm] = []
    try:
        r = redis_client()
        for price in prices():
            s = int(await r.get(_key(price, "shown")) or 0)
            t = int(await r.get(_key(price, "tapped")) or 0)
            arms.append(Arm(price, s, t))
    except Exception:  # noqa: BLE001
        log.warning("price_probe_read_failed", exc_info=True)
        return {"ready": False, "reason": "counters unavailable", "arms": []}

    total = sum(a.shown for a in arms)
    baseline = max((a.rate for a in arms if a.shown), default=0.0) or 0.03
    need = required_per_arm(baseline, min_detectable_lift())
    smallest = min((a.shown for a in arms), default=0)

    out = {
        "arms": [
            {
                "price": a.price,
                "shown": a.shown,
                "tapped": a.tapped,
                "rate": round(a.rate, 4),
                "revenue_per_impression": round(a.revenue_per_impression, 4),
            }
            for a in arms
        ],
        "impressions": total,
        "needed_per_arm": need,
        "ready": smallest >= need,
    }

    if not out["ready"]:
        out["reason"] = (
            f"{smallest:,} impressions on the thinnest arm, need about {need:,}. "
            "Reading it now would be reading noise."
        )
        return out

    ranked = sorted(arms, key=lambda a: -a.revenue_per_impression)
    best, second = ranked[0], ranked[1]
    z = abs(_z(best, second))
    out["leader"] = best.price
    out["significant"] = z >= 1.96
    out["z"] = round(z, 2)
    out["verdict"] = (
        f"${best.price} earns {best.revenue_per_impression:.3f} per impression "
        f"against ${second.price} at {second.revenue_per_impression:.3f}"
        + ("." if z >= 1.96 else " — but the gap is inside the noise, so treat them as tied.")
    )
    return out


# ── CLI ──────────────────────────────────────────────────────────────────


def print_plan() -> None:
    """`python -m app.priceprobe` — what the probe needs before it can speak.

    Deliberately runs with no database and no Redis: the useful output here is
    the arithmetic on how much traffic a price test costs, and that is worth
    seeing before deciding whether to run one at all.
    """
    arms = prices()
    print(f"\n  PRICE PROBE — {len(arms)} arms: " + ", ".join(f"${p}" for p in arms))
    print(f"  Annual shown at {annual_multiple():g}x monthly "
          f"({', '.join(f'${round(p * annual_multiple())}' for p in arms)}/yr)\n")

    print("  HOW MUCH TRAFFIC A READABLE RESULT COSTS")
    print("  (impressions needed PER ARM, 95% confidence, 80% power)\n")
    print(f"  {'if paywall converts at':<24}{'to see a 20% gap':>18}{'a 50% gap':>14}{'a 2x gap':>12}")
    for baseline in (0.01, 0.02, 0.03, 0.05, 0.10):
        row = "".join(
            f"{required_per_arm(baseline, lift):>14,}"
            for lift in (0.20, 0.50, 1.00)
        )
        print(f"  {baseline * 100:>5.0f}%{'':<18}{row}")

    print("\n  WHAT THAT MEANS")
    n2 = required_per_arm(0.03, 1.00)
    n_small = required_per_arm(0.03, 0.20)
    print(f"  At a 3% paywall tap-through, telling $5 from $10 (a 2x gap in")
    print(f"  conversion terms) needs about {n2:,} impressions per arm.")
    print(f"  Telling $8 from $10 needs about {n_small:,} — {n_small // max(1, n2)}x more.\n")
    print("  So: two arms, far apart. A three-way $5/$8/$10 test at launch")
    print("  traffic will not resolve, and you will act on noise anyway.")
    print("  Run $5 against $10. Read revenue per impression, not conversion.\n")
    print("  The email list from the 'tell me when it opens' screen is the")
    print("  other half of the result, and it does not need significance to")
    print("  be useful — those are the people to talk to.\n")


if __name__ == "__main__":  # pragma: no cover
    print_plan()
