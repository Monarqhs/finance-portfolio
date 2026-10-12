"""Tests for the Portfolio Risk & Concentration module.

Covers docs/02-analysis-specs/01. Portfolio Risk & Concentration.md
numbered Test cases 1:1 (TC-01 .. TC-12).
"""
from analyst.risk import (
    Classification,
    Holding,
    analyze_risk,
)


def _flat(n, value=100.0):
    return [value] * n


def test_tc01_weights_sum_to_100():
    holdings = [
        Holding("SMH", 40.0, _flat(300)),
        Holding("MU", 30.0, _flat(300)),
        Holding("SKHY", 15.0, _flat(300)),
        Holding("CASH", 15.0, []),
    ]
    r = analyze_risk(holdings)
    assert abs(sum(r.weights.values()) - 1.0) < 1e-4


def test_tc02_sector_concentration_flag():
    holdings = [
        Holding("SMH", 40.0, _flat(300)),
        Holding("MU", 30.0, _flat(300)),
        Holding("SKHY", 15.0, _flat(300)),
        Holding("CASH", 15.0, []),
    ]
    r = analyze_risk(holdings)
    assert abs(r.largest_sector_weight - 0.85) < 1e-6
    assert any(f.code == "SECTOR_OVERCONCENTRATED" for f in r.flags)


def test_tc03_single_factor_lookthrough():
    # MU 10% + SKHY 10% (memory 1.0) + SMH 35% (memory 0.20 look-through)
    # memory factor = 0.10 + 0.10 + 0.35*0.20 = 0.27 -> below default 0.60.
    holdings = [
        Holding("MU", 10.0, _flat(300)),
        Holding("SKHY", 10.0, _flat(300)),
        Holding("SMH", 35.0, _flat(300)),
        Holding("CASH", 45.0, []),
    ]
    r = analyze_risk(holdings)
    assert abs(r.memory_factor_weight - 0.27) < 1e-6
    assert not any(f.code == "SINGLE_FACTOR" for f in r.flags)

    # Heavier memory tilt crosses the threshold.
    holdings2 = [
        Holding("MU", 40.0, _flat(300)),
        Holding("SKHY", 30.0, _flat(300)),
        Holding("CASH", 30.0, []),
    ]
    r2 = analyze_risk(holdings2)
    assert r2.memory_factor_weight >= 0.60
    assert any(f.code == "SINGLE_FACTOR" for f in r2.flags)


def test_tc04_hhi():
    two = analyze_risk([Holding("MU", 50.0, _flat(300)), Holding("SKHY", 50.0, _flat(300))])
    assert abs(two.hhi - 5000) < 1e-6
    one = analyze_risk([Holding("MU", 100.0, _flat(300))])
    assert abs(one.hhi - 10000) < 1e-6
    four = analyze_risk([
        Holding("MU", 25.0, _flat(300)),
        Holding("SKHY", 25.0, _flat(300)),
        Holding("AMD", 25.0, _flat(300)),
        Holding("VOO", 25.0, _flat(300)),
    ])
    assert abs(four.hhi - 2500) < 1e-6


def test_tc05_volatility():
    r = analyze_risk([Holding("MU", 100.0, _flat(300))])
    assert r.volatility["MU"] == 0.0


def test_tc06_max_drawdown():
    # Keep the peak-to-trough drop inside the 252-day lookback window.
    series = [100.0] * 50 + [100, 120, 60, 90]
    r = analyze_risk([Holding("MU", 100.0, series)])
    assert r.max_drawdown["MU"] == -50.0


def test_tc07_correlation_flag():
    # Two identical price series -> correlation 1.0 -> HIGH_CORRELATION.
    series = [100 + i for i in range(300)]
    r = analyze_risk([
        Holding("MU", 50.0, list(series)),
        Holding("SKHY", 50.0, list(series)),
    ])
    assert r.avg_correlation is not None and abs(r.avg_correlation - 1.0) < 1e-6
    assert any(f.code == "HIGH_CORRELATION" for f in r.flags)


def test_tc08_relative_return():
    # Portfolio one holding -4.4% over 1w; benchmark -4.1%.
    port = [100.0] * 300
    port[-6:] = [100, 100, 100, 100, 100, 95.6]  # ~ -4.4% over 5 days
    bench = [100.0] * 300
    bench[-6:] = [100, 100, 100, 100, 100, 95.9]  # ~ -4.1%
    r = analyze_risk([Holding("MU", 100.0, port)], benchmarks={"SMH": bench})
    assert r.relative_return["SMH"] is not None
    # Relative ~ -0.3 (portfolio slightly worse than benchmark).
    assert r.relative_return["SMH"] < 0


def test_tc09_low_cash_flag():
    low = analyze_risk([Holding("MU", 95.0, _flat(300)), Holding("CASH", 5.0, [])])
    assert any(f.code == "LOW_CASH_BUFFER" for f in low.flags)
    ok = analyze_risk([Holding("MU", 80.0, _flat(300)), Holding("CASH", 20.0, [])])
    assert not any(f.code == "LOW_CASH_BUFFER" for f in ok.flags)


def test_tc10_insufficient_history_excluded_not_fatal():
    r = analyze_risk([
        Holding("MU", 50.0, _flat(300)),
        Holding("SKHY", 50.0, [100.0]),  # only one point
    ])
    assert r.volatility["SKHY"] is None
    assert any("SKHY" in n for n in r.notes)
    assert r.volatility["MU"] == 0.0  # others still computed


def test_tc11_no_price_for_holding():
    # A holding with empty history still contributes to allocation; its risk
    # metrics are marked unavailable, run still produces a result.
    r = analyze_risk([
        Holding("MU", 60.0, _flat(300)),
        Holding("AMD", 40.0, []),
    ])
    assert "AMD" in r.weights
    assert r.volatility["AMD"] is None
    assert isinstance(r.hhi, float)


def test_tc12_evidence_attached():
    holdings = [
        Holding("SMH", 40.0, _flat(300)),
        Holding("MU", 30.0, _flat(300)),
        Holding("SKHY", 30.0, _flat(300)),
    ]
    r = analyze_risk(holdings)
    for f in r.flags:
        assert f.evidence and f.limitation
