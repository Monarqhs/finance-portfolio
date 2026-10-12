"""Tests for the Analyst Narrative (Gemini) layer.

Covers docs/02-analysis-specs/05. Analyst Narrative (Gemini).md numbered Test
cases 1:1 (TC-01 .. TC-08). Uses a mocked LLM; no network.
"""
from dataclasses import dataclass

from analyst.narrative import (
    DeidentifiedPayload,
    build_deidentified_payload,
    contains_real_amount,
    deterministic_summary,
    generate_narrative,
)


# --- lightweight stand-ins for module outputs ------------------------------ #
@dataclass
class _Tag:
    code: str
    evidence: str


class _Macro:
    tags = [_Tag("YIELDS_RISING", "10Y yield +18 bps over 1w.")]


class _Risk:
    largest_sector_weight = 0.85
    memory_factor_weight = 0.62
    top1_weight = 0.53
    hhi = 4200


class _Opp:
    class _S:
        ticker = "XLV"
        total = 5
        correlation_to_semi = 0.12
    ranked = [_S()]


def _payload():
    return build_deidentified_payload(
        positions=[{"label": "Position A", "kind": "semiconductor ETF",
                    "weight_pct": 53.0, "change_pct": -2.2}],
        macro=_Macro(), risk=_Risk(), opportunities=_Opp(),
        headlines=["Bond yields rose this week."],
    )


def test_tc01_deidentification():
    p = _payload()
    # No real currency amounts, no ticker tied to an amount.
    assert not contains_real_amount(p)
    blob = str(p.positions)
    assert "Rp" not in blob and "$" not in blob


def test_tc02_scrubber_blocks_leakage():
    p = _payload()
    p.positions.append({"label": "leak", "amount": "Rp6.205.207"})
    called = {"n": 0}

    def llm(_):
        called["n"] += 1
        return "ok"

    out = generate_narrative(p, llm, api_key="KEY")
    assert out.source == "deterministic-fallback"
    assert called["n"] == 0  # LLM never called


def test_tc03_banned_phrase_rejected():
    p = _payload()
    out = generate_narrative(p, lambda _: "The market will crash next week.", api_key="KEY")
    assert out.source == "deterministic-fallback"


def test_tc04_ungrounded_number_rejected():
    p = _payload()
    # 9999 does not appear anywhere in the payload.
    out = generate_narrative(p, lambda _: "Sector is 9999 percent concentrated.", api_key="KEY")
    assert out.source == "deterministic-fallback"


def test_tc05_happy_path():
    p = _payload()
    good = "Market read: yields rose. Largest sector 85 percent. Limitation: context only."
    out = generate_narrative(p, lambda _: good, api_key="KEY")
    assert out.source == "llm"
    assert "yields rose" in out.text


def test_tc06_missing_key_fallback():
    p = _payload()
    out = generate_narrative(p, lambda _: "unused", api_key=None)
    assert out.source == "deterministic-fallback"


def test_tc07_api_error_fallback():
    p = _payload()

    def boom(_):
        raise RuntimeError("api down")

    out = generate_narrative(p, boom, api_key="KEY")
    assert out.source == "deterministic-fallback"


def test_tc08_deterministic_summary_self_sufficient():
    p = _payload()
    text = deterministic_summary(p)
    assert "Market read" in text
    assert "Portfolio read" in text
    assert "Concentration & opportunities" in text
    assert "Risks to watch" in text
