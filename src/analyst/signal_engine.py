"""Signal engine: shared technical primitives and the signal decision ladder.

Implements docs/02-analysis-specs/04. Signal Engine.md.

All primitives are pure functions over a list of close prices (oldest first,
newest last) and are reused by the Risk and Opportunity modules so the math is
defined once. The signal decision carries the predecessor's BUY/HOLD/CAUTION
priority ladder, returning an evidence + limitation contract for every label.

Nothing here predicts prices; labels classify current conditions only.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

# Trading-day conventions used across the project.
WEEK = 5
MONTH = 21
YEAR = 252


# --------------------------------------------------------------------------- #
# Primitives (pure functions over a close-price series)                        #
# --------------------------------------------------------------------------- #
def sma(closes: list[float], n: int) -> float | None:
    """Simple moving average of the last ``n`` closes. None if fewer than n."""
    if n <= 0 or len(closes) < n:
        return None
    return sum(closes[-n:]) / n


def rsi(closes: list[float], period: int = 14) -> float | None:
    """Wilder's RSI. None if fewer than ``period + 1`` closes.

    Returns 100.0 when there are no losses over the window.
    """
    if len(closes) < period + 1:
        return None
    gains = 0.0
    losses = 0.0
    for i in range(1, period + 1):
        delta = closes[i] - closes[i - 1]
        if delta >= 0:
            gains += delta
        else:
            losses -= delta
    avg_gain = gains / period
    avg_loss = losses / period
    for i in range(period + 1, len(closes)):
        delta = closes[i] - closes[i - 1]
        gain = delta if delta > 0 else 0.0
        loss = -delta if delta < 0 else 0.0
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def drawdown_from_high(closes: list[float], lookback: int = YEAR) -> float | None:
    """Current price's percent distance below the rolling-max over ``lookback``.

    Negative = below the period peak. This is the "how far below the 52w high is
    the latest price" measure used by the signal/discount logic. For the
    peak-to-trough worst decline, use ``max_drawdown``.
    """
    if not closes:
        return None
    window = closes[-lookback:] if len(closes) >= lookback else closes
    peak = max(window)
    if peak <= 0:
        return None
    return (closes[-1] / peak - 1) * 100


def max_drawdown(closes: list[float], lookback: int = YEAR) -> float | None:
    """Worst peak-to-trough decline over ``lookback``, in percent (<= 0).

    Distinct from ``drawdown_from_high``: this scans the whole window for the
    deepest drop from any running peak to a later trough. Shared with the Risk
    module (max drawdown metric).
    """
    if not closes:
        return None
    window = closes[-lookback:] if len(closes) >= lookback else closes
    peak = window[0]
    worst = 0.0
    for price in window:
        if price > peak:
            peak = price
        if peak > 0:
            dd = (price / peak - 1) * 100
            if dd < worst:
                worst = dd
    return worst


def daily_returns(closes: list[float]) -> list[float]:
    """Simple daily returns from a close series."""
    return [
        closes[i] / closes[i - 1] - 1
        for i in range(1, len(closes))
        if closes[i - 1]
    ]


def volatility(closes: list[float]) -> float | None:
    """Annualized volatility: stdev of daily returns * sqrt(252).

    None if fewer than two returns. Shared with the Risk module.
    """
    rets = daily_returns(closes)
    if len(rets) < 2:
        return None
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    return math.sqrt(var) * math.sqrt(YEAR)


def change_pct(closes: list[float], periods: int) -> float | None:
    """Percent change over ``periods`` trading days. None if not enough data."""
    if len(closes) <= periods:
        return None
    prev = closes[-1 - periods]
    if not prev:
        return None
    return (closes[-1] / prev - 1) * 100


# --------------------------------------------------------------------------- #
# Signal decision                                                              #
# --------------------------------------------------------------------------- #
@dataclass
class Signal:
    """A condition classification, never a trade instruction or forecast."""

    label: str
    evidence: str
    limitation: str
    extras: dict = field(default_factory=dict)


_LIMITATION = (
    "Trend/momentum read of current conditions, not a price forecast."
)


def signal_from_series(closes: list[float]) -> Signal:
    """Classify a close series into the BUY/HOLD/CAUTION priority ladder.

    Priority (docs/02-analysis-specs/04):
      1. Insufficient history (SMA200 or RSI unavailable) -> NEUTRAL/LIMITED DATA
      2. Broken trend (price < SMA200)                    -> CAUTION
      3. Uptrend (price > SMA200, and > SMA50 if present) -> BUY/HOLD by RSI
      4. Consolidation (above SMA200, below SMA50)        -> NEUTRAL/DCA
    """
    if len(closes) < 2:
        return Signal(
            label="NEUTRAL / LIMITED DATA",
            evidence="Not enough price history to compute a trend.",
            limitation=_LIMITATION,
        )

    price = closes[-1]
    s50 = sma(closes, 50)
    s200 = sma(closes, 200)
    r = rsi(closes, 14)
    dd = drawdown_from_high(closes, YEAR)

    # 1. Insufficient history: never treat a missing SMA200 as a broken trend.
    if s200 is None or r is None:
        wk = change_pct(closes, WEEK)
        soft = f" 1w change {wk:+.1f}%." if wk is not None else ""
        return Signal(
            label="NEUTRAL / LIMITED DATA",
            evidence=f"SMA200/RSI unavailable (history too short).{soft}",
            limitation=_LIMITATION + " Newly listed names lack a full trend.",
            extras={"rsi": r, "sma200": s200, "drawdown": dd},
        )

    # 2. Broken trend wins over any momentum reading.
    if price < s200:
        return Signal(
            label="CAUTION",
            evidence=f"Price below SMA200 (long-term trend weak); RSI {r:.0f}.",
            limitation=_LIMITATION,
            extras={"rsi": r, "sma200": s200, "drawdown": dd},
        )

    # 3. Uptrend (above SMA200, and above SMA50 when available).
    uptrend = price > s200 and (s50 is None or price > s50)
    if uptrend:
        if r >= 70:
            return Signal(
                label="HOLD / THIN DCA",
                evidence=f"Uptrend but RSI {r:.0f} (overbought); don't chase.",
                limitation=_LIMITATION,
                extras={"rsi": r, "sma200": s200, "drawdown": dd},
            )
        discount = dd is not None and dd <= -10
        if r <= 30:
            bonus = f" Price {dd:.0f}% below 52w high." if discount else ""
            return Signal(
                label="BUY (OVERSOLD)",
                evidence=f"Intact trend above SMA200 and RSI {r:.0f} (oversold).{bonus}",
                limitation=_LIMITATION,
                extras={"rsi": r, "sma200": s200, "drawdown": dd, "discount": discount},
            )
        bonus = f" Discount: {dd:.0f}% below 52w high." if discount else ""
        return Signal(
            label="BUY (HEALTHY MOMENTUM)",
            evidence=f"Above SMA50 & SMA200, RSI {r:.0f} (healthy).{bonus}",
            limitation=_LIMITATION,
            extras={"rsi": r, "sma200": s200, "drawdown": dd, "discount": discount},
        )

    # 4. Above SMA200 but below SMA50: consolidation.
    return Signal(
        label="NEUTRAL / DCA",
        evidence=f"Above SMA200 but below SMA50 (consolidation); RSI {r:.0f}.",
        limitation=_LIMITATION,
        extras={"rsi": r, "sma200": s200, "drawdown": dd},
    )
