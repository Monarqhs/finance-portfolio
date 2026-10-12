"""Tests for the Macro & Currency module.

Covers docs/02-analysis-specs/02. Macro & Currency.md numbered Test cases 1:1
(TC-01 .. TC-09).
"""
from analyst.macro import BANNED_PREDICTIVE_PHRASES, analyze_macro
from analyst.sources.fred import SeriesObs


def _obs(sid, latest, week_ago=None, month_ago=None):
    o = SeriesObs(series_id=sid, latest=latest, week_ago=week_ago, month_ago=month_ago)
    if week_ago is not None:
        o.change_1w = latest - week_ago
    if month_ago is not None:
        o.change_1m = latest - month_ago
    return o


def test_tc01_rates_panel_deltas():
    series = {"DGS10": _obs("DGS10", 4.30, week_ago=4.10, month_ago=4.00)}
    r = analyze_macro(series, None, None)
    assert abs(series["DGS10"].change_1w - 0.20) < 1e-9
    assert abs(series["DGS10"].change_1m - 0.30) < 1e-9
    assert "DGS10" in r.rates


def test_tc02_yields_rising_tag():
    # +18 bps = +0.18 pp over 1w -> raised.
    series = {"DGS10": _obs("DGS10", 4.28, week_ago=4.10)}
    r = analyze_macro(series, None, None)
    assert any(t.code == "YIELDS_RISING" for t in r.tags)

    # +5 bps -> not raised.
    series2 = {"DGS10": _obs("DGS10", 4.15, week_ago=4.10)}
    r2 = analyze_macro(series2, None, None)
    assert not any(t.code == "YIELDS_RISING" for t in r2.tags)


def test_tc03_curve_tags():
    up = {"T10Y2Y": _obs("T10Y2Y", 0.30, week_ago=0.18)}  # +12 bps
    assert any(t.code == "CURVE_STEEPENING" for t in analyze_macro(up, None, None).tags)
    down = {"T10Y2Y": _obs("T10Y2Y", 0.06, week_ago=0.18)}  # -12 bps
    assert any(t.code == "CURVE_FLATTENING" for t in analyze_macro(down, None, None).tags)


def test_tc04_risk_off_level_and_jump():
    level = {"VIXCLS": _obs("VIXCLS", 27.0, week_ago=26.0)}
    assert any(t.code == "RISK_OFF" for t in analyze_macro(level, None, None).tags)
    jump = {"VIXCLS": _obs("VIXCLS", 22.0, week_ago=18.0)}  # +22%
    assert any(t.code == "RISK_OFF" for t in analyze_macro(jump, None, None).tags)
    calm = {"VIXCLS": _obs("VIXCLS", 15.0, week_ago=15.0)}
    assert not any(t.code == "RISK_OFF" for t in analyze_macro(calm, None, None).tags)


def test_tc05_rupiah_tag():
    r = analyze_macro({}, usdidr_now=17200.0, usdidr_1w=17000.0)  # +1.18%
    assert any(t.code == "RUPIAH_WEAKENING" for t in r.tags)


def test_tc06_portfolio_linkage_requires_risk_input():
    series = {"DGS10": _obs("DGS10", 4.30, week_ago=4.10)}  # yields rising
    r = analyze_macro(series, None, None, memory_factor_weight=0.70)
    assert r.linkage_note is not None
    assert "70%" in r.linkage_note


def test_tc07_ai_bubble_block_is_non_forecast():
    r = analyze_macro(
        {"VIXCLS": _obs("VIXCLS", 28.0, week_ago=20.0),
         "DGS10": _obs("DGS10", 4.30, week_ago=4.10)},
        None, None,
        memory_factor_weight=0.80,
        synchronized_drawdown=True,
    )
    block = r.ai_bubble_context.lower()
    assert "not a prediction" in block
    for phrase in BANNED_PREDICTIVE_PHRASES:
        assert phrase not in block


def test_tc08_missing_series_non_fatal():
    series = {"VIXCLS": SeriesObs("VIXCLS", error="unavailable")}
    r = analyze_macro(series, None, None)
    assert not any(t.code == "RISK_OFF" for t in r.tags)
    assert any("VIXCLS" in n for n in r.notes)


def test_tc09_evidence_attached():
    series = {
        "DGS10": _obs("DGS10", 4.30, week_ago=4.10),
        "T10Y2Y": _obs("T10Y2Y", 0.30, week_ago=0.18),
    }
    r = analyze_macro(series, 17200.0, 17000.0)
    assert r.tags
    for t in r.tags:
        assert t.evidence and t.limitation
