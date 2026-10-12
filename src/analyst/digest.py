"""Weekly digest: assemble module outputs into the HTML email.

Implements docs/03-delivery/01. Weekly Digest (Email).md.

Python builds the full report with real IDR amounts (the narrative layer never
sees these). Each section renders independently and degrades to a note on error
(fail-safe). A single-column layout keeps it readable on mobile.
"""
from __future__ import annotations

import datetime as dt
import html
from dataclasses import dataclass, field

DISCLAIMER = (
    "Informational only; not financial advice. This report describes current "
    "conditions and never predicts prices."
)


@dataclass
class DigestInput:
    """Everything the digest needs. Any field may be None/flagged -> degrades."""

    date: dt.date
    total_value_idr: float | None = None
    week_change_pct: float | None = None
    narrative_text: str = ""
    narrative_source: str = "deterministic-fallback"
    positions: list[dict] = field(default_factory=list)  # full, real amounts
    realized_pnl_idr: float | None = None
    risk: object | None = None
    macro: object | None = None
    opportunities: object | None = None
    signals: dict[str, object] = field(default_factory=dict)
    section_errors: dict[str, str] = field(default_factory=dict)


def _rp(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"Rp{value:,.0f}".replace(",", ".")


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:+.2f}%"


def _section(title: str, body_html: str, error: str | None = None) -> str:
    if error:
        body_html = f"<p class='note'>Section unavailable: {html.escape(error)}</p>"
    return f"<section><h2>{html.escape(title)}</h2>{body_html}</section>"


def _header(d: DigestInput) -> str:
    badge = "LLM" if d.narrative_source == "llm" else "deterministic"
    return (
        f"<header><h1>Weekly Portfolio Analyst — {d.date.isoformat()}</h1>"
        f"<p>Total value: <strong>{_rp(d.total_value_idr)}</strong> "
        f"({_pct(d.week_change_pct)} this week)</p>"
        f"<p class='badge'>Analyst note source: {badge}</p></header>"
    )


def _analyst_note(d: DigestInput) -> str:
    text = html.escape(d.narrative_text).replace("\n", "<br>")
    return _section("Analyst note", f"<p>{text}</p>", d.section_errors.get("narrative"))


def _positions(d: DigestInput) -> str:
    if d.section_errors.get("positions"):
        return _section("Positions & P&L", "", d.section_errors["positions"])
    rows = ["<tr><th>Holding</th><th>Value</th><th>Weight</th>"
            "<th>Unrealized</th><th>Asset P&L</th><th>FX P&L</th></tr>"]
    for p in d.positions:
        rows.append(
            f"<tr><td>{html.escape(str(p.get('ticker','')))}</td>"
            f"<td>{_rp(p.get('market_value_idr'))}</td>"
            f"<td>{p.get('weight_pct','n/a')}%</td>"
            f"<td>{_rp(p.get('total_unrealized_idr'))}</td>"
            f"<td>{_rp(p.get('asset_pnl_idr'))}</td>"
            f"<td>{_rp(p.get('fx_pnl_idr'))}</td></tr>"
        )
    body = f"<table>{''.join(rows)}</table>"
    body += f"<p>Realized P&L to date: <strong>{_rp(d.realized_pnl_idr)}</strong></p>"
    return _section("Positions & P&L", body)


def _risk(d: DigestInput) -> str:
    if d.risk is None or d.section_errors.get("risk"):
        return _section("Portfolio risk", "", d.section_errors.get("risk", "no data"))
    r = d.risk
    items = [
        f"Largest sector: {r.largest_sector} {r.largest_sector_weight*100:.0f}%",
        f"Memory-factor exposure: {r.memory_factor_weight*100:.0f}%",
        f"Top holding: {r.top1_weight*100:.0f}%",
        f"HHI: {r.hhi:.0f}",
        f"Avg correlation: {'n/a' if r.avg_correlation is None else f'{r.avg_correlation:.2f}'}",
    ]
    flags = "".join(
        f"<li><strong>{html.escape(f.code)}</strong>: {html.escape(f.evidence)} "
        f"<em>({html.escape(f.limitation)})</em></li>"
        for f in r.flags
    )
    body = "<ul>" + "".join(f"<li>{html.escape(i)}</li>" for i in items) + "</ul>"
    body += f"<ul class='flags'>{flags}</ul>"
    return _section("Portfolio risk", body)


def _macro(d: DigestInput) -> str:
    if d.macro is None or d.section_errors.get("macro"):
        return _section("Macro & currency", "", d.section_errors.get("macro", "no data"))
    m = d.macro
    tags = "".join(
        f"<li><strong>{html.escape(t.code)}</strong>: {html.escape(t.evidence)} "
        f"<em>({html.escape(t.limitation)})</em></li>"
        for t in m.tags
    )
    body = f"<ul class='tags'>{tags or '<li>No notable regime shifts.</li>'}</ul>"
    if m.linkage_note:
        body += f"<p>{html.escape(m.linkage_note)}</p>"
    if m.ai_bubble_context:
        body += f"<p class='context'>{html.escape(m.ai_bubble_context)}</p>"
    return _section("Macro & currency", body)


def _opportunities(d: DigestInput) -> str:
    if d.opportunities is None or d.section_errors.get("opportunities"):
        return _section("Opportunities", "", d.section_errors.get("opportunities", "no data"))
    rows = []
    for s in d.opportunities.ranked:
        corr = "n/a" if s.correlation_to_semi is None else f"{s.correlation_to_semi:.2f}"
        rows.append(
            f"<li><strong>{html.escape(s.ticker)}</strong> (score {s.total}, "
            f"corr-to-semi {corr}): {html.escape(s.rationale)} "
            f"<em>({html.escape(s.limitation)})</em></li>"
        )
    body = f"<ul>{''.join(rows) or '<li>No candidates scored.</li>'}</ul>"
    return _section("Opportunities (sector ETFs)", body)


def _signals(d: DigestInput) -> str:
    if not d.signals or d.section_errors.get("signals"):
        return _section("Signals", "", d.section_errors.get("signals", "no data"))
    rows = []
    for ticker, sig in d.signals.items():
        rows.append(
            f"<li><strong>{html.escape(ticker)}</strong>: "
            f"{html.escape(sig.label)} — {html.escape(sig.evidence)} "
            f"<em>({html.escape(sig.limitation)})</em></li>"
        )
    return _section("Signals", f"<ul>{''.join(rows)}</ul>")


def _footer() -> str:
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    return (
        f"<footer><p class='disclaimer'>{html.escape(DISCLAIMER)}</p>"
        f"<p class='meta'>Sources: Yahoo Finance, FRED, Google Sheet ledger. "
        f"Generated {now}Z.</p></footer>"
    )


_STYLE = (
    "<style>body{font-family:sans-serif;max-width:680px;margin:0 auto;padding:12px;"
    "line-height:1.5}section{margin:18px 0}table{width:100%;border-collapse:collapse}"
    "th,td{text-align:left;padding:4px;border-bottom:1px solid #eee;font-size:14px}"
    ".badge{font-size:12px;color:#555}.note,.disclaimer{color:#777;font-size:12px}"
    ".context{background:#fafafa;padding:8px;border-left:3px solid #ccc}"
    "em{color:#777;font-size:12px}</style>"
)


def render_digest(d: DigestInput) -> str:
    """Assemble the full HTML email, degrading any failed section to a note."""
    parts = [
        "<!doctype html><html><head><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width, initial-scale=1'>",
        _STYLE, "</head><body>",
        _header(d),
        _analyst_note(d),
        _positions(d),
        _risk(d),
        _macro(d),
        _opportunities(d),
        _signals(d),
        _footer(),
        "</body></html>",
    ]
    return "".join(parts)
