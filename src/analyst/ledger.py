"""Ledger: derive positions and P&L from a transaction list.

Implements the derivation rules in
docs/01-data-sources/01. Ledger (Google Sheet).md.

This module is pure: it takes a list of transaction dicts (already read from the
owner's Google Sheet elsewhere) and computes positions, weighted-average cost,
realized/unrealized P&L, and the explicit asset-vs-FX currency-effect split.
It never performs network or Sheet I/O, so it is fully unit-testable offline.
"""
from __future__ import annotations

from dataclasses import dataclass, field

REQUIRED_FIELDS = ("date", "ticker", "action", "quantity", "price_usd", "usdidr")


@dataclass
class Position:
    """Derived state for a single ticker."""

    ticker: str
    qty: float = 0.0
    avg_cost_usd: float = 0.0  # weighted-average cost per unit (USD)
    cost_basis_usd: float = 0.0  # qty * avg_cost_usd
    cost_basis_idr: float = 0.0  # sum of qty * price_usd * usdidr at each BUY
    realized_usd: float = 0.0

    @property
    def is_open(self) -> bool:
        # Treat tiny residuals from fractional trades as closed.
        return self.qty > 1e-12


@dataclass
class LedgerResult:
    positions: dict[str, Position] = field(default_factory=dict)
    skipped: list[dict] = field(default_factory=list)  # malformed rows + reason

    def open_positions(self) -> dict[str, Position]:
        return {t: p for t, p in self.positions.items() if p.is_open}


def _clean_row(raw: dict) -> tuple[dict | None, str | None]:
    """Validate and normalize one raw row. Returns (clean, None) or (None, reason)."""
    for f in REQUIRED_FIELDS:
        if raw.get(f) in (None, ""):
            return None, f"missing required field '{f}'"
    try:
        row = {
            "date": str(raw["date"]).strip(),
            "ticker": str(raw["ticker"]).strip().upper(),
            "action": str(raw["action"]).strip().upper(),
            "quantity": float(raw["quantity"]),
            "price_usd": float(raw["price_usd"]),
            "fee_usd": float(raw.get("fee_usd") or 0.0),
            "usdidr": float(raw["usdidr"]),
            "note": str(raw.get("note") or "").strip(),
        }
    except (TypeError, ValueError) as exc:
        return None, f"unparseable numeric value: {exc}"
    if row["action"] not in ("BUY", "SELL"):
        return None, f"invalid action '{row['action']}'"
    if row["quantity"] <= 0:
        return None, "quantity must be positive"
    return row, None


def _sort_key(row: dict, idx: int) -> tuple[str, int]:
    # Chronological by date, then stable by original row order for same-day rows.
    return (row["date"], idx)


def derive_positions(rows: list[dict]) -> LedgerResult:
    """Fold a list of transaction rows into positions and P&L.

    Weighted-average-cost method (see spec):
      BUY : cost_basis += qty*price + fee ; qty += qty ; avg = cost_basis/qty
      SELL: realized   += qty*(sell - avg) - fee ; qty -= qty ; basis = avg*qty
    """
    result = LedgerResult()

    cleaned: list[dict] = []
    for i, raw in enumerate(rows):
        row, reason = _clean_row(raw)
        if row is None:
            result.skipped.append({"row": raw, "reason": reason})
        else:
            cleaned.append((row, i))

    cleaned.sort(key=lambda ri: _sort_key(ri[0], ri[1]))

    for row, _ in cleaned:
        t = row["ticker"]
        pos = result.positions.setdefault(t, Position(ticker=t))
        qty = row["quantity"]
        price = row["price_usd"]
        fee = row["fee_usd"]
        fx = row["usdidr"]

        if row["action"] == "BUY":
            pos.cost_basis_usd += qty * price + fee
            pos.cost_basis_idr += qty * price * fx
            pos.qty += qty
            pos.avg_cost_usd = pos.cost_basis_usd / pos.qty if pos.qty else 0.0
        else:  # SELL
            sell_qty = min(qty, pos.qty)  # cannot sell more than held
            pos.realized_usd += sell_qty * (price - pos.avg_cost_usd) - fee
            # Reduce IDR basis proportionally to the fraction of shares sold.
            if pos.qty:
                frac = sell_qty / pos.qty
                pos.cost_basis_idr *= 1 - frac
            pos.qty -= sell_qty
            pos.cost_basis_usd = pos.avg_cost_usd * pos.qty  # avg unchanged
            if pos.qty <= 1e-12:
                pos.qty = 0.0
                pos.cost_basis_usd = 0.0
                pos.cost_basis_idr = 0.0

    return result


@dataclass
class PnL:
    """Unrealized P&L for an open position, with the asset/FX split."""

    ticker: str
    qty: float
    unrealized_usd: float
    market_value_idr: float
    asset_pnl_idr: float  # price move only, cost held at entry FX
    fx_pnl_idr: float  # FX move only, on the cost basis
    total_unrealized_idr: float  # asset + fx (must reconcile)


def unrealized_pnl(pos: Position, current_price: float, usdidr_now: float) -> PnL:
    """Compute unrealized P&L and the asset-vs-FX currency-effect split.

    asset_pnl_idr : (current_price - avg_cost) * qty, valued at ENTRY FX
                    (i.e. the average entry FX implied by cost_basis_idr).
    fx_pnl_idr    : cost basis revalued from entry FX to current FX.
    The two sum to total IDR unrealized P&L (reconciliation guaranteed by
    construction below).
    """
    qty = pos.qty
    unrealized_usd = qty * (current_price - pos.avg_cost_usd)

    # Average entry FX implied by the IDR cost basis.
    cost_basis_usd = pos.avg_cost_usd * qty
    entry_fx = pos.cost_basis_idr / cost_basis_usd if cost_basis_usd else usdidr_now

    market_value_idr = qty * current_price * usdidr_now
    # Total is defined as market value (now FX) minus cost basis (entry FX).
    total_unrealized_idr = market_value_idr - pos.cost_basis_idr
    # Asset component: price move valued at entry FX.
    asset_pnl_idr = unrealized_usd * entry_fx
    # FX component is the remainder, so the split always reconciles exactly.
    fx_pnl_idr = total_unrealized_idr - asset_pnl_idr

    return PnL(
        ticker=pos.ticker,
        qty=qty,
        unrealized_usd=unrealized_usd,
        market_value_idr=market_value_idr,
        asset_pnl_idr=asset_pnl_idr,
        fx_pnl_idr=fx_pnl_idr,
        total_unrealized_idr=total_unrealized_idr,
    )
