"""Opportunity scanner: rank sector/thematic ETFs as diversification candidates.

Implements docs/02-analysis-specs/03. Opportunity Scanner (Sector ETFs).md.

Scores a watchlist of ETFs on a transparent additive scale (trend + momentum +
low-correlation-to-semi + discount + regime fit) and surfaces the top candidates
for reducing the portfolio's semiconductor concentration. Deterministic and
auditable. Never says "buy"; ranks current conditions, does not predict returns.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from analyst.signal_engine import (
    daily_returns,
    drawdown_from_high,
    rsi,
    sma,
)
from analyst.risk import _correlation

# Default ETF universe. rationale explains the diversification role.
DEFAULT_WATCHLIST = {
    "XLV": "Health Care — defensive, low correlation to semis",
    "XLE": "Energy — inflation / geopolitical hedge",
    "XLF": "Financials — benefits when yields rise",
    "XLU": "Utilities — defensive + AI power-demand proxy",
    "XLP": "Consumer Staples — risk-off harbor",
    "GLD": "Gold — geopolitical hedge",
}

# Maps a macro regime tag to the ETF that benefits from it (regime-fit bonus).
REGIME_FIT = {
    "YIELDS_RISING": {"XLF"},
    "RISK_OFF": {"XLV", "XLP", "XLU", "GLD"},
    "DOLLAR_WEAK": {"GLD"},
}

BANNED_BUY_PHRASES = ("buy now", "you should buy", "must buy", "buy it", "sell")


@dataclass
class Score:
    ticker: str
    total: int
    trend: int
    momentum: int
    diversification: int
    discount: int
    regime_fit: int
    correlation_to_semi: float | None
    rsi: float | None
    rationale: str
    limitation: str


@dataclass
class Opportunities:
    ranked: list[Score] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _trend_points(closes: list[float]) -> int:
    price = closes[-1]
    s50 = sma(closes, 50)
    s200 = sma(closes, 200)
    if s200 is None:
        return 0
    if price > s200 and (s50 is None or price > s50):
        return 2
    if price > s200:
        return 1
    return -1  # below SMA200


def _momentum_points(r: float | None) -> int:
    if r is None:
        return 0
    if 40 <= r <= 65:
        return 1
    if r > 70 or r < 30:
        return -1
    return 0  # 30-40 or 65-70


def _diversification_points(corr: float | None) -> int:
    if corr is None:
        return 0
    if corr < 0.3:
        return 2
    if corr <= 0.5:
        return 1
    if corr <= 0.7:
        return 0
    return -1


def _discount_points(closes: list[float]) -> int:
    dd = drawdown_from_high(closes)
    s200 = sma(closes, 200)
    intact = s200 is not None and closes[-1] > s200
    if intact and dd is not None and -20 <= dd <= -10:
        return 1
    return 0


def scan_opportunities(
    etf_closes: dict[str, list[float]],
    semi_reference: list[float],
    active_tags: list[str] | None = None,
    watchlist: dict[str, str] | None = None,
    top_n: int = 3,
) -> Opportunities:
    """Score and rank the ETF watchlist. ``semi_reference`` is the correlation base."""
    wl = watchlist or DEFAULT_WATCHLIST
    active = set(active_tags or [])
    semi_ret = daily_returns(semi_reference)

    scores: list[Score] = []
    notes: list[str] = []
    for ticker, rationale_base in wl.items():
        closes = etf_closes.get(ticker, [])
        if sma(closes, 200) is None:
            notes.append(f"{ticker}: insufficient history, excluded from scoring.")
            continue
        r = rsi(closes, 14)
        corr = _correlation(daily_returns(closes), semi_ret)

        trend = _trend_points(closes)
        momentum = _momentum_points(r)
        diversification = _diversification_points(corr)
        discount = _discount_points(closes)
        regime = 1 if ticker in {
            t for tag in active for t in REGIME_FIT.get(tag, set())
        } else 0

        total = trend + momentum + diversification + discount + regime
        fit_note = ""
        if regime:
            matched = [tag for tag in active if ticker in REGIME_FIT.get(tag, set())]
            fit_note = f" Fits active regime ({', '.join(matched)})."
        scores.append(Score(
            ticker=ticker,
            total=total,
            trend=trend,
            momentum=momentum,
            diversification=diversification,
            discount=discount,
            regime_fit=regime,
            correlation_to_semi=corr,
            rsi=r,
            rationale=(
                f"{rationale_base}. Correlation to semi "
                f"{'n/a' if corr is None else f'{corr:.2f}'}.{fit_note} "
                f"Candidate to consider for reducing concentration."
            ),
            limitation=(
                "Ranking of current conditions, not a return forecast and not a "
                "recommendation to buy."
            ),
        ))

    scores.sort(key=lambda s: s.total, reverse=True)
    return Opportunities(ranked=scores[:top_n] if top_n else scores, notes=notes)
