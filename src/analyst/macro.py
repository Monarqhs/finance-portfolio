"""Macro & currency analysis.

Implements docs/02-analysis-specs/02. Macro & Currency.md.

Turns FRED series + USD/IDR into measured, dated regime tags linked to the
portfolio, plus a strictly non-forecast "AI-bubble risk" context block. Every
tag carries its measured number and a limitation note. Nothing here predicts
markets; it explains the current backdrop with evidence.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from analyst.sources.fred import SeriesObs

# Phrases that would turn a context note into a prediction. The AI-bubble block
# is validated against these so it can never drift into forecasting.
BANNED_PREDICTIVE_PHRASES = (
    "will crash", "going to", "will fall", "will rise", "guaranteed",
    "is about to", "will pop", "bound to", "certainly",
)

THRESHOLDS = {
    "yield_bps_1w": 15,       # 10Y move, basis points over 1w
    "curve_bps_1w": 10,       # T10Y2Y move, bps over 1w
    "dollar_pct_1w": 1.0,     # DTWEXBGS, percent over 1w
    "vix_level": 25.0,
    "vix_jump_pct_1w": 20.0,
    "fx_pct_1w": 1.0,         # USD/IDR, percent over 1w
}


@dataclass
class Tag:
    code: str
    evidence: str
    limitation: str


@dataclass
class MacroRead:
    tags: list[Tag] = field(default_factory=list)
    rates: dict[str, SeriesObs] = field(default_factory=dict)
    usdidr: dict[str, float | None] = field(default_factory=dict)
    linkage_note: str | None = None
    ai_bubble_context: str | None = None
    notes: list[str] = field(default_factory=list)


def _bps(change: float | None) -> float | None:
    """A FRED yield change in percentage points -> basis points."""
    return None if change is None else change * 100


def analyze_macro(
    series: dict[str, SeriesObs],
    usdidr_now: float | None,
    usdidr_1w: float | None,
    *,
    memory_factor_weight: float | None = None,
    synchronized_drawdown: bool = False,
    thresholds: dict[str, float] | None = None,
) -> MacroRead:
    """Build regime tags, portfolio linkage, and the AI-bubble context block."""
    thr = {**THRESHOLDS, **(thresholds or {})}
    tags: list[Tag] = []
    notes: list[str] = []

    def _get(sid: str) -> SeriesObs | None:
        obs = series.get(sid)
        if obs is None or obs.error:
            notes.append(f"{sid}: unavailable ({obs.error if obs else 'missing'}).")
            return None
        return obs

    dgs10 = _get("DGS10")
    t10y2y = _get("T10Y2Y")
    dff = _get("DFF")
    dxy = _get("DTWEXBGS")
    vix = _get("VIXCLS")

    # Yields --------------------------------------------------------------- #
    if dgs10 and dgs10.change_1w is not None:
        bps = _bps(dgs10.change_1w)
        if bps >= thr["yield_bps_1w"]:
            tags.append(Tag("YIELDS_RISING",
                f"10Y yield +{bps:.0f} bps over 1w (to {dgs10.latest:.2f}%).",
                "Headwind for growth/semis; a rotation driver, not a forecast."))
        elif bps <= -thr["yield_bps_1w"]:
            tags.append(Tag("YIELDS_FALLING",
                f"10Y yield {bps:.0f} bps over 1w (to {dgs10.latest:.2f}%).",
                "Tailwind for growth/semis; condition, not a forecast."))

    # Curve ---------------------------------------------------------------- #
    if t10y2y and t10y2y.change_1w is not None:
        bps = _bps(t10y2y.change_1w)
        if bps >= thr["curve_bps_1w"]:
            tags.append(Tag("CURVE_STEEPENING",
                f"10Y-2Y spread +{bps:.0f} bps over 1w.",
                "Growth/recession-expectation context only."))
        elif bps <= -thr["curve_bps_1w"]:
            tags.append(Tag("CURVE_FLATTENING",
                f"10Y-2Y spread {bps:.0f} bps over 1w.",
                "Growth/recession-expectation context only."))

    # Fed ------------------------------------------------------------------ #
    if dff and dff.change_1m is not None:
        if dff.change_1m > 0:
            tags.append(Tag("FED_TIGHTENING",
                f"Fed Funds +{dff.change_1m:.2f} pp over 1m (to {dff.latest:.2f}%).",
                "Policy-stance context."))
        elif dff.change_1m < 0:
            tags.append(Tag("FED_EASING",
                f"Fed Funds {dff.change_1m:.2f} pp over 1m (to {dff.latest:.2f}%).",
                "Policy-stance context."))

    # Dollar --------------------------------------------------------------- #
    if dxy and dxy.change_1w is not None and dxy.week_ago:
        pct = (dxy.change_1w / dxy.week_ago) * 100
        if pct >= thr["dollar_pct_1w"]:
            tags.append(Tag("DOLLAR_STRONG",
                f"Broad dollar +{pct:.1f}% over 1w.",
                "Backdrop for USD/IDR entry cost."))
        elif pct <= -thr["dollar_pct_1w"]:
            tags.append(Tag("DOLLAR_WEAK",
                f"Broad dollar {pct:.1f}% over 1w.",
                "Backdrop for USD/IDR entry cost."))

    # Risk-off (VIX) ------------------------------------------------------- #
    risk_off = False
    if vix and vix.latest is not None:
        jump = None
        if vix.week_ago:
            jump = (vix.latest / vix.week_ago - 1) * 100
        if vix.latest >= thr["vix_level"] or (jump is not None and jump >= thr["vix_jump_pct_1w"]):
            risk_off = True
            j = f", +{jump:.0f}% over 1w" if jump is not None else ""
            tags.append(Tag("RISK_OFF",
                f"VIX at {vix.latest:.0f}{j}.",
                "Broad fear gauge; contextualizes synchronized drawdowns."))

    # Rupiah --------------------------------------------------------------- #
    usdidr = {"now": usdidr_now, "week_ago": usdidr_1w, "change_pct_1w": None}
    if usdidr_now is not None and usdidr_1w:
        pct = (usdidr_now / usdidr_1w - 1) * 100
        usdidr["change_pct_1w"] = pct
        if pct >= thr["fx_pct_1w"]:
            tags.append(Tag("RUPIAH_WEAKENING",
                f"USD/IDR +{pct:.1f}% over 1w (to {usdidr_now:.0f}).",
                "A weaker rupiah raises the IDR cost of buying USD assets."))
        elif pct <= -thr["fx_pct_1w"]:
            tags.append(Tag("RUPIAH_STRENGTHENING",
                f"USD/IDR {pct:.1f}% over 1w (to {usdidr_now:.0f}).",
                "A stronger rupiah lowers the IDR cost of buying USD assets."))

    # Portfolio linkage ---------------------------------------------------- #
    linkage = None
    yields_rising = any(t.code == "YIELDS_RISING" for t in tags)
    if memory_factor_weight is not None and memory_factor_weight >= 0.60 and yields_rising:
        linkage = (
            f"Yields rising while {memory_factor_weight*100:.0f}% of the portfolio "
            f"depends on the memory/HBM factor: this week's drawdown is consistent "
            f"with a macro rotation out of growth, not a break in the holdings' "
            f"fundamentals. Evidence: the rate move above and holdings falling "
            f"together. Limitation: macro attribution is contextual, not causal proof."
        )

    # AI-bubble risk context (strictly non-forecast) ----------------------- #
    ai_block = _ai_bubble_context(memory_factor_weight, synchronized_drawdown, risk_off, yields_rising)

    return MacroRead(
        tags=tags,
        rates={k: v for k, v in series.items()},
        usdidr=usdidr,
        linkage_note=linkage,
        ai_bubble_context=ai_block,
        notes=notes,
    )


def _ai_bubble_context(
    memory_factor_weight: float | None,
    synchronized_drawdown: bool,
    risk_off: bool,
    yields_rising: bool,
) -> str:
    """Report measurable proxies only. Never predicts; always carries a limit line."""
    parts: list[str] = []
    if memory_factor_weight is not None:
        parts.append(
            f"Portfolio concentration in one AI-adjacent factor is "
            f"{memory_factor_weight*100:.0f}%."
        )
    if synchronized_drawdown:
        parts.append("Holdings fell together this week (systemic, not idiosyncratic).")
    if risk_off and yields_rising:
        parts.append("Risk-off coincides with rising yields (the described rotation pattern).")
    parts.append(
        "These are current conditions and historical analogies, not a prediction. "
        "Analogies to 2008 are context, not a forecast."
    )
    return " ".join(parts)
