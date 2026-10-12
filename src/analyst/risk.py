"""Portfolio risk & concentration analysis.

Implements docs/02-analysis-specs/01. Portfolio Risk & Concentration.md.

Consumes derived positions (ledger) + current prices + price history and
produces allocation, concentration metrics (top-1/top-3, sector, single-factor
with ETF look-through, HHI), risk metrics (volatility, max drawdown, average
pairwise correlation), relative return, and evidence-first concentration flags.

Deterministic and auditable. No price prediction; flags describe current
conditions with evidence and a limitation note, and never say "sell".
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from analyst.signal_engine import daily_returns, max_drawdown, volatility

# --------------------------------------------------------------------------- #
# Classification (static, in-repo; no PII). ticker -> sector/theme/class.      #
# ETF look-through: fraction of an ETF's weight attributed to a theme, so the  #
# SMH <-> SK Hynix / memory overlap is captured.                               #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Classification:
    sector: str
    theme: str
    asset_class: str
    # Fraction of this holding's weight to attribute to the memory/HBM factor
    # via look-through (e.g. SMH holds some memory names). 1.0 for direct
    # memory names, 0.0 for unrelated.
    memory_factor: float = 0.0


DEFAULT_CLASSIFICATION: dict[str, Classification] = {
    "SMH": Classification("Information Technology", "Semiconductors (broad)", "ETF", memory_factor=0.20),
    "MU": Classification("Information Technology", "Memory/HBM", "Stock", memory_factor=1.0),
    "SKHY": Classification("Information Technology", "Memory/HBM", "Stock", memory_factor=1.0),
    "AMD": Classification("Information Technology", "Semiconductors (logic)", "Stock", memory_factor=0.0),
    "VOO": Classification("Broad market", "Broad market", "ETF", memory_factor=0.0),
    "GC=F": Classification("Commodity", "Gold/geopolitical hedge", "Commodity", memory_factor=0.0),
    "CASH": Classification("Cash", "Cash", "Cash", memory_factor=0.0),
    "RDPU": Classification("Cash", "Money market / RDPU", "Cash", memory_factor=0.0),
}

# Tickers treated as cash for the cash-buffer metric.
CASH_TICKERS = {"CASH", "RDPU"}


@dataclass
class Holding:
    """Input holding for the risk module (post-ledger, with market value)."""

    ticker: str
    market_value_idr: float
    closes: list[float] = field(default_factory=list)  # ~1y daily closes


@dataclass
class Flag:
    code: str
    severity: str  # "red" | "amber" | "info"
    evidence: str
    limitation: str


@dataclass
class RiskResult:
    weights: dict[str, float]  # ticker -> weight fraction (incl. CASH)
    top1_weight: float
    top3_weight: float
    largest_sector: str
    largest_sector_weight: float
    memory_factor_weight: float
    hhi: float
    volatility: dict[str, float | None]
    max_drawdown: dict[str, float | None]
    avg_correlation: float | None
    relative_return: dict[str, float | None]
    flags: list[Flag] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# Default thresholds (configurable).                                           #
# --------------------------------------------------------------------------- #
THRESHOLDS = {
    "sector_overconcentrated": 0.70,
    "single_factor": 0.60,
    "top1_heavy": 0.40,
    "high_correlation": 0.70,
    "low_cash_buffer": 0.10,
}


def _correlation(a: list[float], b: list[float]) -> float | None:
    """Pearson correlation of two aligned return series."""
    n = min(len(a), len(b))
    if n < 2:
        return None
    a, b = a[-n:], b[-n:]
    ma, mb = sum(a) / n, sum(b) / n
    cov = sum((a[i] - ma) * (b[i] - mb) for i in range(n))
    va = math.sqrt(sum((x - ma) ** 2 for x in a))
    vb = math.sqrt(sum((x - mb) ** 2 for x in b))
    if va == 0 or vb == 0:
        return None
    return cov / (va * vb)


def analyze_risk(
    holdings: list[Holding],
    classification: dict[str, Classification] | None = None,
    benchmarks: dict[str, list[float]] | None = None,
    thresholds: dict[str, float] | None = None,
) -> RiskResult:
    """Compute allocation, concentration, risk metrics, and flags."""
    cls = classification or DEFAULT_CLASSIFICATION
    thr = {**THRESHOLDS, **(thresholds or {})}
    benchmarks = benchmarks or {}

    total = sum(h.market_value_idr for h in holdings)
    weights: dict[str, float] = {}
    if total > 0:
        for h in holdings:
            weights[h.ticker] = h.market_value_idr / total

    # Concentration ------------------------------------------------------- #
    sorted_w = sorted(weights.values(), reverse=True)
    top1 = sorted_w[0] if sorted_w else 0.0
    top3 = sum(sorted_w[:3])
    hhi = sum((w * 100) ** 2 for w in weights.values())  # 0..10000

    sector_weight: dict[str, float] = {}
    memory_factor_weight = 0.0
    for h in holdings:
        c = cls.get(h.ticker, Classification("Unknown", "Unknown", "Unknown"))
        w = weights.get(h.ticker, 0.0)
        sector_weight[c.sector] = sector_weight.get(c.sector, 0.0) + w
        memory_factor_weight += w * c.memory_factor
    largest_sector, largest_sector_weight = (
        max(sector_weight.items(), key=lambda kv: kv[1]) if sector_weight else ("", 0.0)
    )

    # Risk metrics -------------------------------------------------------- #
    vol: dict[str, float | None] = {}
    mdd: dict[str, float | None] = {}
    return_series: dict[str, list[float]] = {}
    notes: list[str] = []
    for h in holdings:
        if h.ticker in CASH_TICKERS:
            continue
        if len(h.closes) < 2:
            vol[h.ticker] = None
            mdd[h.ticker] = None
            notes.append(f"{h.ticker}: insufficient history for risk metrics.")
            continue
        vol[h.ticker] = volatility(h.closes)
        mdd[h.ticker] = max_drawdown(h.closes)
        return_series[h.ticker] = daily_returns(h.closes)

    # Average pairwise correlation among holdings with history.
    corr_tickers = list(return_series.keys())
    corrs: list[float] = []
    for i in range(len(corr_tickers)):
        for j in range(i + 1, len(corr_tickers)):
            c = _correlation(return_series[corr_tickers[i]], return_series[corr_tickers[j]])
            if c is not None:
                corrs.append(c)
    avg_corr = sum(corrs) / len(corrs) if corrs else None

    # Relative return vs benchmarks (1w) ---------------------------------- #
    rel: dict[str, float | None] = {}
    port_ret_1w = _portfolio_return(holdings, weights, periods=5)
    for name, series in benchmarks.items():
        b = _series_return(series, 5)
        rel[name] = (port_ret_1w - b) if (port_ret_1w is not None and b is not None) else None

    # Flags (evidence-first) ---------------------------------------------- #
    flags: list[Flag] = []
    if largest_sector_weight >= thr["sector_overconcentrated"]:
        flags.append(Flag(
            "SECTOR_OVERCONCENTRATED", "red",
            f"{largest_sector_weight*100:.0f}% in one sector ({largest_sector}).",
            "A sector shock would hit almost the whole portfolio; condition, not a forecast.",
        ))
    if memory_factor_weight >= thr["single_factor"]:
        flags.append(Flag(
            "SINGLE_FACTOR", "red",
            f"{memory_factor_weight*100:.0f}% exposed to the memory/HBM factor "
            f"(incl. ETF look-through of SMH).",
            "MU, SKHY and SMH's memory sleeve tend to move together; not a prediction.",
        ))
    if top1 >= thr["top1_heavy"]:
        flags.append(Flag(
            "TOP1_HEAVY", "amber",
            f"Top holding is {top1*100:.0f}% of the portfolio.",
            "Single-name size, not a view on that name's future.",
        ))
    if avg_corr is not None and avg_corr >= thr["high_correlation"]:
        flags.append(Flag(
            "HIGH_CORRELATION", "amber",
            f"Average pairwise correlation {avg_corr:.2f} (holdings move together).",
            "Diversification is lower than the number of positions suggests.",
        ))
    cash_w = sum(weights.get(t, 0.0) for t in CASH_TICKERS)
    if cash_w < thr["low_cash_buffer"]:
        flags.append(Flag(
            "LOW_CASH_BUFFER", "amber",
            f"Cash is {cash_w*100:.0f}% of the portfolio (< {thr['low_cash_buffer']*100:.0f}%).",
            "Little dry powder for corrections; condition only.",
        ))
    if not flags:
        flags.append(Flag(
            "WELL_DIVERSIFIED", "info",
            "No concentration threshold breached.",
            "Informational snapshot of current weights.",
        ))

    return RiskResult(
        weights=weights,
        top1_weight=top1,
        top3_weight=top3,
        largest_sector=largest_sector,
        largest_sector_weight=largest_sector_weight,
        memory_factor_weight=memory_factor_weight,
        hhi=hhi,
        volatility=vol,
        max_drawdown=mdd,
        avg_correlation=avg_corr,
        relative_return=rel,
        flags=flags,
        notes=notes,
    )


def _series_return(closes: list[float], periods: int) -> float | None:
    if len(closes) <= periods or not closes[-1 - periods]:
        return None
    return (closes[-1] / closes[-1 - periods] - 1) * 100


def _portfolio_return(
    holdings: list[Holding], weights: dict[str, float], periods: int
) -> float | None:
    """Weighted sum of holding returns over ``periods`` (cash contributes 0)."""
    acc = 0.0
    covered = 0.0
    for h in holdings:
        if h.ticker in CASH_TICKERS:
            covered += weights.get(h.ticker, 0.0)
            continue
        r = _series_return(h.closes, periods)
        w = weights.get(h.ticker, 0.0)
        if r is not None:
            acc += w * r
            covered += w
    return acc if covered > 0 else None
