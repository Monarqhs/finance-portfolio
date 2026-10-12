"""Tests for the Signal Engine.

Covers the numbered Test cases in docs/02-analysis-specs/04. Signal Engine.md
1:1 (TC-01 .. TC-10).
"""
import math

from analyst.signal_engine import (
    change_pct,
    drawdown_from_high,
    max_drawdown,
    rsi,
    signal_from_series,
    sma,
    volatility,
)


def _series(trend_up: bool, n: int = 260, start: float = 100.0, step: float = 1.0):
    """Build a monotonic series of length n (for a clean trend/SMA200)."""
    if trend_up:
        return [start + i * step for i in range(n)]
    return [start + (n - i) * step for i in range(n)]


def test_tc01_sma():
    assert sma([1, 2, 3, 4], 2) == 3.5
    assert sma([1, 2], 3) is None


def test_tc02_rsi_bounds():
    rising = [float(i) for i in range(1, 30)]
    falling = [float(i) for i in range(30, 1, -1)]
    assert rsi(rising, 14) == 100.0  # no losses
    assert rsi(falling, 14) < 1.0  # all losses -> near 0
    assert rsi([1, 2, 3], 14) is None  # len < period + 1


def test_tc03_drawdown():
    # Max drawdown = worst peak-to-trough (120 -> 60) = -50%.
    assert max_drawdown([100, 120, 60, 90], lookback=252) == -50.0
    # Current distance from high = latest (90) vs peak (120) = -25%.
    assert drawdown_from_high([100, 120, 60, 90], lookback=252) == -25.0


def test_tc04_volatility():
    assert volatility([100, 100, 100, 100]) == 0.0
    # Known synthetic returns: +10%, -10%, +10% ... compare to hand calc.
    closes = [100, 110, 99, 108.9]
    rets = [110 / 100 - 1, 99 / 110 - 1, 108.9 / 99 - 1]
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    expected = math.sqrt(var) * math.sqrt(252)
    assert abs(volatility(closes) - expected) < 1e-6


def test_tc05_change_pct():
    closes = [10, 11, 12, 13, 14, 20]  # 6 points -> 1w change uses close[-6]
    assert abs(change_pct(closes, 5) - (20 / 10 - 1) * 100) < 1e-9


def test_tc06_broken_trend_wins():
    # Downtrend series: price far below SMA200, even if RSI is low.
    closes = _series(trend_up=False)
    sig = signal_from_series(closes)
    assert sig.label == "CAUTION"


def test_tc07_overbought_uptrend():
    # Uptrend then a sharp final push to force RSI >= 70.
    closes = _series(trend_up=True)
    closes = closes[:-3] + [closes[-4] * 1.5, closes[-4] * 1.8, closes[-4] * 2.2]
    sig = signal_from_series(closes)
    assert sig.label == "HOLD / THIN DCA"


def test_tc08_healthy_momentum_with_discount():
    # Long steady uptrend establishes SMA50/SMA200 well below current price,
    # then a single intraday spike creates a 52w peak the latest close sits
    # ~11% below -> discount, while price stays above SMA50 and RSI stays
    # healthy (mixed recent moves, not a one-directional run).
    base = [100.0 + i * 2.0 for i in range(255)]  # strong uptrend
    spike = base[-1] * 1.15  # a transient high that defines the 52w peak
    tail = [spike, base[-1] * 1.03, base[-1] * 1.0, base[-1] * 1.02, base[-1] * 1.01]
    closes = base + tail
    sig = signal_from_series(closes)
    assert sig.label == "BUY (HEALTHY MOMENTUM)"
    assert sig.extras.get("drawdown") is not None and sig.extras["drawdown"] <= -10


def test_tc09_insufficient_history_not_caution():
    # Fewer than 200 points -> SMA200 is None -> must be NEUTRAL/LIMITED DATA.
    closes = _series(trend_up=False, n=50)
    sig = signal_from_series(closes)
    assert sig.label == "NEUTRAL / LIMITED DATA"
    assert sig.label != "CAUTION"


def test_tc10_evidence_and_limitation_present():
    for closes in (_series(True), _series(False), _series(True, n=50)):
        sig = signal_from_series(closes)
        assert sig.evidence and sig.limitation
