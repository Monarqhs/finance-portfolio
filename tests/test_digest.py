"""Tests for the Weekly Digest.

Covers docs/03-delivery/01. Weekly Digest (Email).md numbered Test cases 1:1
(TC-01 .. TC-08). Builds the email from fixture module outputs; no send.
"""
import datetime as dt
from dataclasses import dataclass, field

from analyst.digest import DigestInput, render_digest


# --- fixture stand-ins for module outputs ---------------------------------- #
@dataclass
class _Flag:
    code: str
    evidence: str
    limitation: str


@dataclass
class _Risk:
    largest_sector: str = "Information Technology"
    largest_sector_weight: float = 0.85
    memory_factor_weight: float = 0.62
    top1_weight: float = 0.53
    hhi: float = 4200
    avg_correlation: float | None = 0.78
    flags: list = field(default_factory=lambda: [
        _Flag("SECTOR_OVERCONCENTRATED", "85% in one sector.", "condition, not forecast")
    ])


@dataclass
class _Tag:
    code: str
    evidence: str
    limitation: str


@dataclass
class _Macro:
    tags: list = field(default_factory=lambda: [
        _Tag("YIELDS_RISING", "10Y +18 bps over 1w.", "context only")
    ])
    linkage_note: str = "Rotation, not broken fundamentals."
    ai_bubble_context: str = "Concentration 62%. Not a prediction."


@dataclass
class _Score:
    ticker: str = "XLV"
    total: int = 5
    correlation_to_semi: float | None = 0.12
    rationale: str = "Health Care. Candidate to consider for reducing concentration."
    limitation: str = "Ranking of current conditions, not a buy recommendation."


@dataclass
class _Opp:
    ranked: list = field(default_factory=lambda: [_Score()])


@dataclass
class _Sig:
    label: str = "BUY (HEALTHY MOMENTUM)"
    evidence: str = "Above SMA50 & SMA200, RSI 54."
    limitation: str = "Condition, not a forecast."


def _full_input(**overrides):
    base = dict(
        date=dt.date(2026, 10, 12),
        total_value_idr=6_205_207,
        week_change_pct=-4.43,
        narrative_text="Market read: yields rose.",
        narrative_source="llm",
        positions=[{
            "ticker": "SMH", "market_value_idr": 3_382_239, "weight_pct": 53.0,
            "total_unrealized_idr": -74_354, "asset_pnl_idr": -60_000, "fx_pnl_idr": -14_354,
        }],
        realized_pnl_idr=341_809,
        risk=_Risk(), macro=_Macro(), opportunities=_Opp(),
        signals={"SMH": _Sig()},
    )
    base.update(overrides)
    return DigestInput(**base)


def test_tc01_full_assembly():
    html = render_digest(_full_input())
    for title in ("Analyst note", "Positions &amp; P&amp;L", "Portfolio risk",
                  "Macro &amp; currency", "Opportunities", "Signals"):
        assert title in html
    # Order: analyst note before positions before risk before macro.
    assert html.index("Analyst note") < html.index("Positions")
    assert html.index("Positions") < html.index("Portfolio risk")
    assert html.index("Portfolio risk") < html.index("Macro")


def test_tc02_section_degradation():
    d = _full_input(macro=None, section_errors={"macro": "FRED unavailable"})
    html = render_digest(d)
    assert "Section unavailable" in html
    # Other sections still render.
    assert "Portfolio risk" in html and "Opportunities" in html and "Signals" in html


def test_tc03_source_badge():
    assert "source: LLM" in render_digest(_full_input(narrative_source="llm"))
    assert "source: deterministic" in render_digest(
        _full_input(narrative_source="deterministic-fallback")
    )


def test_tc04_amounts_only_in_email_not_narrative():
    d = _full_input(narrative_text="Largest sector 85 percent.")
    html = render_digest(d)
    # The narrative text block contains no Rp amount...
    note_start = html.index("Analyst note")
    note_end = html.index("Positions")
    assert "Rp" not in html[note_start:note_end]
    # ...but the positions section does.
    assert "Rp" in html[note_end:]


def test_tc05_disclaimer_present():
    html = render_digest(_full_input())
    assert "not financial advice" in html
    assert "never predicts prices" in html


def test_tc06_empty_portfolio():
    d = _full_input(positions=[], total_value_idr=0.0)
    html = render_digest(d)
    assert "Realized P&L" in html  # renders gracefully


def test_tc07_mobile_single_column():
    html = render_digest(_full_input())
    assert "viewport" in html
    assert "max-width:680px" in html  # single-column constraint


def test_tc08_no_crash_on_all_none():
    d = DigestInput(date=dt.date(2026, 10, 12))
    html = render_digest(d)  # every optional section None -> notes, no crash
    assert "<html>" in html and "Weekly Portfolio Analyst" in html
