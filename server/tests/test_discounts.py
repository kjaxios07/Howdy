"""Tests for the discounts module.

Discounts are the easiest topic in the product to get wrong, for two reasons:
a made-up discount reads exactly like a real one, and concession eligibility
differs by state — travelling on a concession you are not entitled to is a
fine, not a saving. So most of these tests are about what the code must
*refuse* to do: guess a state, emit an unverified link, or state an amount.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import appconfig, sources  # noqa: E402

QUESTIONS = Path(__file__).parents[2] / "knowledge" / "questions.json"


def bank() -> list[dict]:
    return json.loads(QUESTIONS.read_text(encoding="utf-8"))["questions"]


# ── Postcode → state ─────────────────────────────────────────────────────

def test_known_postcodes_map_to_the_right_state():
    cases = {
        "4110": "QLD",   # Acacia Ridge, Brisbane — the founder's own example
        "4000": "QLD",
        "2000": "NSW",
        "2170": "NSW",
        "3000": "VIC",
        "3800": "VIC",
        "5000": "SA",
        "6000": "WA",
        "7000": "TAS",
        "2600": "ACT",
        "0800": "NT",
    }
    for postcode, expected in cases.items():
        assert appconfig.state_for_postcode(postcode) == expected, postcode


def test_act_is_not_swallowed_by_the_nsw_range():
    """ACT postcodes sit inside the NSW block. Getting this wrong sends a
    Canberra student to Transport for NSW."""
    assert appconfig.state_for_postcode("2599") == "NSW"
    assert appconfig.state_for_postcode("2600") == "ACT"
    assert appconfig.state_for_postcode("2618") == "ACT"
    assert appconfig.state_for_postcode("2619") == "NSW"


def test_a_bad_postcode_returns_nothing_rather_than_guessing():
    for junk in ("", "abc", "41", "411000", "0000", "9999999"):
        assert appconfig.state_for_postcode(junk) == "", junk


def test_state_names_and_codes_both_resolve():
    for value in ("qld", "QLD", " Qld ", "Queensland", "queensland"):
        assert appconfig.normalise_state(value) == "QLD", value
    assert appconfig.normalise_state("Narnia") == ""


# ── The guide itself ─────────────────────────────────────────────────────

def test_a_brisbane_postcode_gets_queensland_links():
    guide = sources.build_discount_guide(postcode="4110", category="transport")
    assert guide["state"] == "QLD"
    assert guide["known_state"] is True
    assert guide["state_name"] == "Queensland"
    domains = " ".join(link["url"] for link in guide["local"])
    assert "translink.com.au" in domains


def test_an_unknown_location_admits_it_instead_of_defaulting():
    """Defaulting to NSW because it is the biggest state would be the obvious
    shortcut and would quietly give most students the wrong rules."""
    guide = sources.build_discount_guide(postcode="", state="", category="transport")
    assert guide["known_state"] is False
    assert guide["state"] == ""
    assert guide["local"] == []
    # National options still work without knowing where they live.
    assert guide["national"]


def test_every_url_the_guide_emits_is_on_the_allowlist():
    """These links are built by us, so they never pass through verify_reply.
    This is the only place an unverified URL could reach a student."""
    for state in appconfig.discount_states():
        guide = sources.build_discount_guide(state=state)
        for link in guide["local"] + guide["national"]:
            host = sources._host_of(link["url"])
            assert sources.is_trusted(host), f"{state}: {link['url']} is not allowlisted"


def test_unidays_real_host_is_allowlisted():
    """UNiDAYS lives at myunidays.com. 'unidays.com' does not cover it, so the
    link was silently dropped until the host was added."""
    assert sources.is_trusted("myunidays.com")
    guide = sources.build_discount_guide(state="VIC")
    assert any("unidays" in link["url"] for link in guide["national"])


def test_all_eight_states_and_territories_are_covered():
    states = appconfig.discount_states()
    assert set(states) == {"NSW", "VIC", "QLD", "SA", "WA", "TAS", "ACT", "NT"}
    for code, entry in states.items():
        assert entry["transport"]["url"], code
        assert entry["government"]["url"], code
        assert entry["state_name"], code


# ── The eligibility warning ──────────────────────────────────────────────

def test_transport_carries_the_eligibility_warning():
    guide = sources.build_discount_guide(postcode="2000", category="transport")
    assert guide["caution"]
    assert "not automatically entitled" in guide["caution"].lower()


def test_an_unknown_category_defaults_to_cautious():
    """Fail towards the warning, not away from it."""
    guide = sources.build_discount_guide(postcode="2000", category="nonsense")
    assert guide["caution"]


def test_a_harmless_category_does_not_cry_wolf():
    """A warning on every single answer stops being read."""
    guide = sources.build_discount_guide(postcode="2000", category="retail")
    assert guide["caution"] == ""


# ── Link, never list ─────────────────────────────────────────────────────

def test_the_config_states_no_amounts_or_offers():
    """The moment a percentage or a price lives in config it is a fact we have
    to keep true. Amounts are searched live or not given at all."""
    blob = json.dumps(appconfig.discounts())
    for token in ("%", "$", "half price", "50 per cent"):
        assert token not in blob.lower(), f"config contains an amount: {token!r}"


def test_state_urls_are_roots_not_deep_links():
    """Deep concession pages get restructured every year. A dead link is worse
    for a student than one extra click, so we link the site and search the page."""
    for code, entry in appconfig.discount_states().items():
        for key in ("transport", "government"):
            url = entry[key]["url"]
            path = url.split("://", 1)[-1].split("/", 1)
            assert len(path) == 1 or path[1] == "", f"{code}.{key} is a deep link: {url}"
            assert entry[key]["find"], f"{code}.{key} has no search phrase"


# ── The prompt rule ──────────────────────────────────────────────────────

def test_the_prompt_forbids_inventing_discounts():
    from app.prompt import system_prompt

    text = system_prompt()
    assert "DISCOUNTS AND CONCESSIONS" in text
    assert "LINK, NEVER LIST" in text
    assert "fare evasion" in text.lower()
    assert "which state" in text.lower()


# ── The question bank ────────────────────────────────────────────────────

def test_discounts_is_a_real_module_with_real_questions():
    from app.modules import MODULE_IDS

    assert "discounts" in MODULE_IDS
    items = [q for q in bank() if q["module"] == "discounts"]
    assert len(items) >= 25, f"only {len(items)} discount questions"


def test_concession_eligibility_questions_are_volatile():
    """Eligibility rules change and differ by state. If these are not marked
    volatile the nightly job never re-checks them and Kip answers from memory."""
    items = [q for q in bank() if q["module"] == "discounts"]
    concession = [q for q in items if "concession" in q["q"].lower()]
    assert len(concession) >= 5
    for q in concession:
        assert q["volatile"] is True, f"{q['id']} must be volatile: {q['q']}"


def test_the_fare_evasion_question_exists():
    """A student who does not know the penalty cannot weigh the risk."""
    joined = " ".join(q["q"].lower() for q in bank())
    assert "not entitled to" in joined


def test_discounts_questions_did_not_get_duplicated_when_they_moved():
    items = bank()
    texts = [q["q"].lower().strip() for q in items]
    assert len(texts) == len(set(texts)), "a question was left behind in its old module"
