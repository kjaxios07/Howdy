"""Is this thing actually working?

Run before a deploy to catch what is missing, and after one to prove it is
serving. `deploy.sh` finishes by curling /api/health, which tells you the
process is up — not that a student can get an answer, that sign-in will
complete, or that the security headers survived.

Every check names what breaks in the real world when it fails, because a
red line reading `google_redirect_uri` helps nobody at 11pm.

    python -m app.preflight            local, no network calls to us
    python -m app.preflight --live     also hit the deployed site
    python -m app.preflight --model    also spend a fraction of a cent on
                                       one real model call

Exit code is 0 only when nothing is broken, so it drops straight into CI or
the end of a deploy script.
"""

from __future__ import annotations

import asyncio
import json
import os
import ssl
import sys
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]

PASS, FAIL, WARN, SKIP = "pass", "fail", "warn", "skip"


@dataclass
class Check:
    name: str
    state: str
    detail: str = ""
    breaks: str = ""          # what a student experiences when this is wrong


@dataclass
class Report:
    checks: list = field(default_factory=list)

    def add(self, name, state, detail="", breaks=""):
        self.checks.append(Check(name, state, detail, breaks))

    @property
    def failures(self):
        return [c for c in self.checks if c.state == FAIL]

    @property
    def ok(self) -> bool:
        return not self.failures


def _cfg() -> dict:
    return json.loads((ROOT / "howdy.config.json").read_text(encoding="utf-8"))


# ── Configuration: the things that are wrong before you even deploy ──────


def config_checks(r: Report) -> str:
    cfg = _cfg()
    domain = cfg.get("app", {}).get("domain", "")

    if not domain or "CHANGE" in domain.upper() or "example" in domain:
        r.add("domain set", FAIL, domain or "(unset)",
              "Caddy has nothing to get a certificate for and the site will not serve")
    else:
        r.add("domain set", PASS, domain)

    email = cfg.get("app", {}).get("admin_email", "")
    if not email or "example.com" in email:
        r.add("admin email", WARN, email or "(unset)",
              "the university enquiry link on the site goes nowhere")
    else:
        r.add("admin email", PASS, email)

    # A placeholder left in a live page is the classic launch embarrassment.
    stale = []
    for f in ("web/index.html", "web/auth.html", "web/chat.html"):
        p = ROOT / f
        if p.is_file():
            t = p.read_text(encoding="utf-8")
            for token in ("CHANGE ME", "example.com", "howdy.example", "CHANGE-ME"):
                if token in t:
                    stale.append(f"{f}: {token}")
    if stale:
        r.add("no placeholders in web pages", FAIL, "; ".join(stale),
              "a visitor sees a placeholder, or a link that goes nowhere")
    else:
        r.add("no placeholders in web pages", PASS)

    # The single most expensive thing to get wrong.
    if cfg.get("web_search", {}).get("enabled", True):
        n = len(cfg.get("sources", {}).get("trusted_domains", []))
        if n < 10:
            r.add("source allowlist", FAIL, f"{n} domains",
                  "search is on with almost no approved sources — answers will cite nothing")
        else:
            r.add("source allowlist", PASS, f"{n} domains")

    caps = cfg.get("budget", {})
    if caps.get("enabled") and caps.get("monthly_cap_usd"):
        r.add("spend ceiling", PASS, f"${caps['monthly_cap_usd']}/mo, ${caps.get('daily_cap_usd')}/day")
    else:
        r.add("spend ceiling", FAIL, "not configured",
              "nothing stops the bill — a good week produces an invoice nobody agreed to")

    llm = cfg.get("llm", {})
    if llm.get("mode") == "gateway":
        r.add("llm route", WARN, f"gateway -> {llm.get('base_url') or '(no base_url!)'}",
              "run `python -m app.gateway check --search` before trusting this")
    else:
        r.add("llm route", PASS, "direct to Anthropic")

    return domain


def secret_checks(r: Report) -> None:
    """Secrets live in files, not env vars — see config.py. Missing ones stop
    the app booting, so finding them here beats finding them in a crash log."""
    needed = {
        "anthropic_key": "Kip cannot answer anything at all",
        "kek_v1": "no conversation can be encrypted, so nothing can be saved",
        "cookie_secret": "the OAuth handshake cannot complete",
        "google_client_secret": "sign-in fails after the Google screen",
        "db_password": "the app cannot reach its database",
    }
    d = Path("/run/secrets")
    if not d.is_dir():
        d = Path("/etc/howdy/secrets")
    if not d.is_dir():
        r.add("secrets present", SKIP, "no secrets directory on this machine",
              "expected when running outside the server")
        return
    missing = [f"{k} ({why})" for k, why in needed.items() if not (d / k).is_file()]
    if missing:
        r.add("secrets present", FAIL, "; ".join(missing))
    else:
        r.add("secrets present", PASS, f"{len(needed)} found in {d}")

    # A world-readable key is the same as no key.
    loose = []
    for k in needed:
        f = d / k
        if f.is_file() and (f.stat().st_mode & 0o077):
            loose.append(f"{k} is {oct(f.stat().st_mode & 0o777)}")
    if loose:
        r.add("secret permissions", FAIL, "; ".join(loose),
              "any process on the box can read the key that decrypts student conversations")
    elif not missing:
        r.add("secret permissions", PASS, "0400/0600")


def oauth_checks(r: Report, domain: str) -> None:
    """The failure everyone hits on their first deploy.

    Google matches redirect URIs by exact string. One wrong scheme, one
    missing www, and sign-in dies after the consent screen with an error the
    student cannot act on.
    """
    base = os.environ.get("HOWDY_BASE_URL", "")
    expected = f"https://{domain}"
    if not base:
        r.add("base URL set", SKIP, "HOWDY_BASE_URL not in this environment",
              "expected when running off the server")
    elif base.rstrip("/") != expected:
        r.add("base URL matches domain", FAIL, f"{base} != {expected}",
              "the OAuth callback goes to the wrong host and sign-in never completes")
    else:
        r.add("base URL matches domain", PASS, base)

    r.add("google redirect URI", WARN,
          f"{expected}/api/auth/callback",
          "this exact string must be in the Google console under Authorised "
          "redirect URIs — Google matches it literally, so a trailing slash or "
          "a missing 's' in https breaks sign-in")


# ── Live: what a student's browser actually receives ─────────────────────


async def live_checks(r: Report, domain: str) -> None:
    import urllib.error
    import urllib.request

    base = f"https://{domain}"

    def fetch(path, timeout=12):
        req = urllib.request.Request(base + path, headers={"User-Agent": "kip-preflight"})
        return urllib.request.urlopen(req, timeout=timeout, context=ssl.create_default_context())

    try:
        resp = await asyncio.to_thread(fetch, "/api/health")
        body = json.loads(resp.read())
        r.add("site responds", PASS, f"HTTP {resp.status}")
        r.add("knowledge base loaded", PASS if body.get("knowledge_base_version") else FAIL,
              body.get("knowledge_base_version", "missing"),
              "Kip has no facts to ground answers in")
        r.add("search domains live", PASS if body.get("searchable_domains", 0) > 10 else FAIL,
              str(body.get("searchable_domains")),
              "the running app disagrees with the config about what it may cite")
    except ssl.SSLCertVerificationError as exc:
        r.add("site responds", FAIL, f"TLS: {exc}",
              "every browser shows a security warning before the page loads")
        return
    except urllib.error.URLError as exc:
        r.add("site responds", FAIL, str(exc),
              "DNS has not propagated, the firewall is closed, or the stack is down")
        return
    except Exception as exc:  # noqa: BLE001
        r.add("site responds", FAIL, f"{type(exc).__name__}: {exc}")
        return

    # Headers. These are the difference between "it loads" and "it is safe".
    try:
        resp = await asyncio.to_thread(fetch, "/")
        h = {k.lower(): v for k, v in resp.headers.items()}
        want = {
            "strict-transport-security": "a downgrade attack can strip HTTPS",
            "content-security-policy": "an injected script could exfiltrate a conversation",
            "x-content-type-options": "a browser can be tricked into running an upload as script",
            "x-frame-options": "the site can be framed and clickjacked",
        }
        missing = [f"{k} ({why})" for k, why in want.items() if k not in h]
        if missing:
            r.add("security headers", FAIL, "; ".join(missing))
        else:
            r.add("security headers", PASS, f"{len(want)} present")

        csp = h.get("content-security-policy", "")
        if csp and "default-src 'self'" not in csp:
            r.add("CSP is restrictive", FAIL, csp[:80],
                  "the page may load scripts and images from anywhere")
        elif csp:
            r.add("CSP is restrictive", PASS, "default-src 'self'")

        if "server" in h:
            r.add("server header hidden", WARN, h["server"],
                  "advertises the exact software version to anyone scanning")
        else:
            r.add("server header hidden", PASS)
    except Exception as exc:  # noqa: BLE001
        r.add("security headers", FAIL, f"{type(exc).__name__}: {exc}")

    for path, why in [
        ("/api/modules", "the site cannot render its topic list"),
        ("/api/quota", "the app cannot tell a student what is left today"),
        ("/api/budget", "the spend guard cannot be read"),
        ("/auth.html", "there is no way to sign in"),
    ]:
        try:
            resp = await asyncio.to_thread(fetch, path)
            r.add(f"GET {path}", PASS if resp.status == 200 else FAIL, f"HTTP {resp.status}", why)
        except Exception as exc:  # noqa: BLE001
            r.add(f"GET {path}", FAIL, f"{type(exc).__name__}", why)


async def model_check(r: Report) -> None:
    """One real call. Costs a fraction of a cent and answers the only question
    that matters: can Kip actually reply to a student?"""
    try:
        from . import gateway

        out = await gateway.check()
        if "error" in out:
            r.add("model reachable", FAIL, out["error"],
                  "every question returns 'Kip is momentarily unavailable'")
            return
        c = out["checks"]
        r.add("model reachable", PASS if c["responded"] else FAIL,
              f"{out['provider']['base_url']}, ${out['cost_usd']:.6f}")
        r.add("prompt caching works", PASS if c.get("prompt_caching") else FAIL,
              c.get("_caching_note", ""),
              "every answer costs about four times what it should")
        r.add("usage accounting works", PASS if c.get("usage_fields") else FAIL,
              c.get("_usage_note", ""),
              "costs are recorded as zero and the spend ceiling never trips")
    except Exception as exc:  # noqa: BLE001
        r.add("model reachable", FAIL, f"{type(exc).__name__}: {exc}")


# ── Output ───────────────────────────────────────────────────────────────

MARK = {PASS: "\033[32m✓\033[0m", FAIL: "\033[31m✗\033[0m",
        WARN: "\033[33m!\033[0m", SKIP: "\033[90m–\033[0m"}


def render(r: Report) -> None:
    print()
    for c in r.checks:
        print(f"  {MARK[c.state]} {c.name:<30} {c.detail}")
        if c.state in (FAIL, WARN) and c.breaks:
            print(f"      \033[90m{c.breaks}\033[0m")

    n = {s: sum(1 for c in r.checks if c.state == s) for s in (PASS, FAIL, WARN, SKIP)}
    print(f"\n  {n[PASS]} passed, {n[FAIL]} failed, {n[WARN]} to check, {n[SKIP]} skipped")
    if r.failures:
        print("\n  \033[31mNot ready.\033[0m Fix the ✗ lines above and run again.\n")
    else:
        print("\n  \033[32mGood to go.\033[0m Anything marked ! is worth a look, "
              "but nothing is broken.\n")


async def run(live: bool = False, model: bool = False) -> Report:
    r = Report()
    domain = config_checks(r)
    secret_checks(r)
    oauth_checks(r, domain)
    if live and domain and "CHANGE" not in domain.upper():
        await live_checks(r, domain)
    if model:
        await model_check(r)
    return r


if __name__ == "__main__":  # pragma: no cover
    report = asyncio.run(run(live="--live" in sys.argv, model="--model" in sys.argv))
    render(report)
    sys.exit(1 if report.failures else 0)
