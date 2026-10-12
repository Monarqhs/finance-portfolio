"""Tests for the Opportunity Scanner.

Covers docs/02-analysis-specs/03. Opportunity Scanner (Sector ETFs).md
numbered Test cases 1:1 (TC-01 .. TC-09).
"""
from analyst.opportunity import (
    BANNED_BUY_PHRASES,
    _diversification_points,
    _discount_points,
    _momentum_points,
    _trend_points,
    scan_opportunities,
)


def _uptrend(n=260, start=100.0, step=1.0):
    return [start + i * step for i in range(n)]


def _downtrend(n=260, start=400.0, step=1.0):
    return [start - i * step for i in range(n)]


def test_tc01_trend_scoring():
    assert _trend_points(_uptrend()) == 2  # above both SMAs
    # Above SMA200 only: a flat-high series (SMA50 ~= price) then a dip that
    # pushes price below SMA50 while the long rise keeps it above SMA200.
    base = _uptrend(n=230)
    plateau = [base[-1]] * 25            # SMA50 catches up to the price level
    dip = [base[-1] * 0.93] * 5          # recent drop below SMA50, above SMA200
    series = base + plateau + dip
    assert _trend_points(series) == 1
    assert _trend_points(_downtrend()) == -1  # below SMA200


def test_tc02_momentum_scoring():
    assert _momentum_points(50) == 1
    assert _momentum_points(68) == 0
    assert _momentum_points(75) == -1
    assert _momentum_points(25) == -1


def test_tc03_diversification_scoring():
    assert _diversification_points(0.1) == 2
    assert _diversification_points(0.4) == 1
    assert _diversification_points(0.6) == 0
    assert _diversification_points(0.8) == -1


def test_tc04_discount_scoring():
    base = _uptrend(n=255)
    peak = base[-1] * 1.15
    discounted = base + [peak, peak * 0.86, peak * 0.86, peak * 0.86, peak * 0.86]
    assert _discount_points(discounted) == 1
    assert _discount_points(_uptrend()) == 0  # no meaningful discount


def test_tc05_regime_fit():
    semi = _uptrend()
    etfs = {"XLF": _uptrend()}
    wl = {"XLF": "Financials"}
    with_tag = scan_opportunities(etfs, semi, active_tags=["YIELDS_RISING"], watchlist=wl)
    assert with_tag.ranked[0].regime_fit == 1
    without = scan_opportunities(etfs, semi, active_tags=[], watchlist=wl)
    assert without.ranked[0].regime_fit == 0


def test_tc06_ranking_order():
    semi = _uptrend()
    # XLV low-corr uptrend (high score); XLE a downtrend (low score).
    etfs = {"XLV": _uptrend(step=0.5), "XLE": _downtrend()}
    wl = {"XLV": "Health", "XLE": "Energy"}
    res = scan_opportunities(etfs, semi, watchlist=wl, top_n=2)
    assert [s.ticker for s in res.ranked] == sorted(
        [s.ticker for s in res.ranked], key=lambda t: -next(s.total for s in res.ranked if s.ticker == t)
    )
    assert res.ranked[0].total >= res.ranked[1].total


def test_tc07_breakdown_present():
    semi = _uptrend()
    res = scan_opportunities({"XLV": _uptrend()}, semi, watchlist={"XLV": "Health"})
    s = res.ranked[0]
    for comp in (s.trend, s.momentum, s.diversification, s.discount, s.regime_fit):
        assert isinstance(comp, int)
    assert s.rsi is not None
    assert s.correlation_to_semi is not None


def test_tc08_insufficient_history_excluded():
    semi = _uptrend()
    res = scan_opportunities({"XNEW": [100, 101, 102]}, semi, watchlist={"XNEW": "New"})
    assert res.ranked == []
    assert any("XNEW" in n for n in res.notes)


def test_tc09_no_buy_language():
    semi = _uptrend()
    res = scan_opportunities({"XLV": _uptrend()}, semi, watchlist={"XLV": "Health"})
    for s in res.ranked:
        low = s.rationale.lower()
        for phrase in BANNED_BUY_PHRASES:
            assert phrase not in low
        assert s.limitation  # non-empty limitation always attached
