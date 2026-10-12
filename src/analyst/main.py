"""Pipeline orchestrator: fetch -> analyze -> narrate -> render -> send.

Implements the pipeline in docs/00-overview/02. Architecture.md. Each stage is
fail-safe: a failing source/section is flagged and the email still ships.

Usage:
  python -m analyst.main --preview   # render to preview.html, do not send
  python -m analyst.main             # render and email the digest
"""
from __future__ import annotations

import argparse
import datetime as dt
import json

from analyst import config
from analyst.digest import DigestInput, render_digest
from analyst.ledger import derive_positions, unrealized_pnl
from analyst.macro import analyze_macro
from analyst.narrative import build_deidentified_payload, generate_narrative
from analyst.opportunity import DEFAULT_WATCHLIST, scan_opportunities
from analyst.risk import DEFAULT_CLASSIFICATION, Holding, analyze_risk
from analyst.signal_engine import signal_from_series
from analyst.sources import fred, yahoo
from analyst.sources.sheet import build_google_fetcher, read_ledger


def _label_for(ticker: str) -> str:
    c = DEFAULT_CLASSIFICATION.get(ticker)
    return c.theme if c else "holding"


def run(preview: bool) -> str:
    """Run the whole pipeline and return the rendered HTML (also sends unless preview)."""
    errors: dict[str, str] = {}
    today = dt.date.today()

    # 1. INGEST -------------------------------------------------------------- #
    # Ledger (owner's Sheet).
    txns: list[dict] = []
    try:
        fetcher = build_google_fetcher(config.SHEET_ID, json.loads(config.GOOGLE_SA_JSON))
        txns = read_ledger(fetcher)
        print(f"[ledger] read {len(txns)} transaction row(s) from the sheet")
    except Exception as exc:  # noqa: BLE001
        errors["positions"] = f"ledger unavailable: {exc}"
        print(f"[ledger] ERROR reading sheet: {exc}")

    ledger = derive_positions(txns)
    # Diagnostics (no amounts): how many rows were skipped and why, and how many
    # open positions resulted. Surfaced to stdout for the Actions log and to the
    # email so an empty report is explainable.
    if ledger.skipped:
        for s in ledger.skipped:
            print(f"[ledger] skipped row: {s['reason']}")
        reasons = "; ".join(sorted({s["reason"] for s in ledger.skipped}))
        errors.setdefault("positions", f"{len(ledger.skipped)} row(s) skipped: {reasons}")
    open_positions = ledger.open_positions()
    tickers = list(open_positions.keys())
    print(f"[ledger] {len(open_positions)} open position(s): {', '.join(tickers) or 'none'}")

    # Prices + USD/IDR.
    all_tickers = list(dict.fromkeys(tickers + config.BENCHMARKS + list(DEFAULT_WATCHLIST)))
    prices = yahoo.fetch_prices(all_tickers)
    usdidr_now = yahoo.fetch_usdidr()
    usdidr_series = yahoo.fetch_closes("IDR=X")
    usdidr_1w = usdidr_series[-6] if len(usdidr_series) >= 6 else None

    # Macro (FRED).
    try:
        fred_series = fred.fetch_all(config.FRED_API_KEY)
    except Exception as exc:  # noqa: BLE001
        fred_series = {}
        errors["macro"] = f"FRED unavailable: {exc}"

    # 2. ANALYZE ------------------------------------------------------------- #
    # Positions -> holdings with market value for risk.
    holdings: list[Holding] = []
    positions_rows: list[dict] = []
    total_value = 0.0
    for ticker, pos in open_positions.items():
        closes = prices.get(ticker, [])
        price = closes[-1] if closes else pos.avg_cost_usd
        pnl = unrealized_pnl(pos, price, usdidr_now or 0)
        holdings.append(Holding(ticker, pnl.market_value_idr, closes))
        total_value += pnl.market_value_idr
        positions_rows.append({
            "ticker": ticker,
            "market_value_idr": pnl.market_value_idr,
            "total_unrealized_idr": pnl.total_unrealized_idr,
            "asset_pnl_idr": pnl.asset_pnl_idr,
            "fx_pnl_idr": pnl.fx_pnl_idr,
        })
    realized = sum(p.realized_usd for p in ledger.positions.values()) * (usdidr_now or 0)

    for row in positions_rows:
        row["weight_pct"] = round(row["market_value_idr"] / total_value * 100, 1) if total_value else 0.0

    risk = analyze_risk(
        holdings,
        benchmarks={b: prices.get(b, []) for b in config.BENCHMARKS},
    ) if holdings else None

    semi_ref = prices.get("SMH", [])
    macro = analyze_macro(
        fred_series, usdidr_now, usdidr_1w,
        memory_factor_weight=(risk.memory_factor_weight if risk else None),
        synchronized_drawdown=_all_down(positions_rows),
    )
    active_tags = [t.code for t in macro.tags]
    opportunities = scan_opportunities(
        {t: prices.get(t, []) for t in DEFAULT_WATCHLIST}, semi_ref, active_tags=active_tags,
    ) if semi_ref else None
    signals = {t: signal_from_series(prices.get(t, [])) for t in tickers if prices.get(t)}

    # 3. NARRATE ------------------------------------------------------------- #
    narrative_text, narrative_source = "", "deterministic-fallback"
    if risk and opportunities:
        deident_positions = [
            {"label": f"Position {chr(65+i)}", "kind": _label_for(r['ticker']),
             "weight_pct": r["weight_pct"]}
            for i, r in enumerate(positions_rows)
        ]
        payload = build_deidentified_payload(deident_positions, macro, risk, opportunities)
        llm_call = None
        if config.GEMINI_API_KEY:
            from analyst.gemini_client import build_gemini_call
            llm_call = build_gemini_call(config.GEMINI_API_KEY)
        else:
            print("[narrative] GEMINI_API_KEY not set -> deterministic fallback")
        narr = generate_narrative(payload, llm_call, api_key=config.GEMINI_API_KEY or None)
        narrative_text, narrative_source = narr.text, narr.source
        print(f"[narrative] source = {narrative_source}")

    # 4. RENDER -------------------------------------------------------------- #
    week_change = _portfolio_week_change(holdings)
    digest = DigestInput(
        date=today,
        total_value_idr=total_value or None,
        week_change_pct=week_change,
        narrative_text=narrative_text,
        narrative_source=narrative_source,
        positions=positions_rows,
        realized_pnl_idr=realized or None,
        risk=risk,
        macro=macro,
        opportunities=opportunities,
        signals=signals,
        section_errors=errors,
    )
    html = render_digest(digest)

    # 5. SEND ---------------------------------------------------------------- #
    if preview:
        with open("preview.html", "w", encoding="utf-8") as fh:
            fh.write(html)
        print("Wrote preview.html (not sent).")
    else:
        from analyst.gmail_sender import send_email
        subject = f"{config.EMAIL_SUBJECT_PREFIX} — {today.isoformat()}"
        ok, msg = send_email(subject, html, config.EMAIL_TO)
        print(("OK: " if ok else "FAILED: ") + msg)
    return html


def _all_down(rows: list[dict]) -> bool:
    return bool(rows) and all(r.get("total_unrealized_idr", 0) < 0 for r in rows)


def _portfolio_week_change(holdings) -> float | None:
    acc, covered = 0.0, 0.0
    total = sum(h.market_value_idr for h in holdings)
    if not total:
        return None
    for h in holdings:
        if len(h.closes) >= 6 and h.closes[-6]:
            w = h.market_value_idr / total
            acc += w * ((h.closes[-1] / h.closes[-6] - 1) * 100)
            covered += w
    return acc if covered > 0 else None


def main() -> None:
    parser = argparse.ArgumentParser(description="Weekly portfolio analyst")
    parser.add_argument("--preview", action="store_true", help="render only, do not send")
    args = parser.parse_args()
    run(preview=args.preview)


if __name__ == "__main__":
    main()
