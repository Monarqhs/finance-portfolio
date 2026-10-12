"""Tests for the Ledger derivation.

Covers the numbered Test cases in
docs/01-data-sources/01. Ledger (Google Sheet).md 1:1 (TC-01 .. TC-10).
"""
from analyst.ledger import derive_positions, unrealized_pnl


def _row(date, ticker, action, qty, price, fx, fee=0, note=""):
    return {
        "date": date,
        "ticker": ticker,
        "action": action,
        "quantity": qty,
        "price_usd": price,
        "fee_usd": fee,
        "usdidr": fx,
        "note": note,
    }


def test_tc01_single_buy():
    res = derive_positions([_row("2026-01-01", "AAA", "BUY", 2, 10, 16000)])
    p = res.positions["AAA"]
    assert p.qty == 2
    assert p.avg_cost_usd == 10
    assert p.cost_basis_usd == 20


def test_tc02_weighted_average_cost():
    res = derive_positions([
        _row("2026-01-01", "AAA", "BUY", 1, 10, 16000),
        _row("2026-01-02", "AAA", "BUY", 3, 20, 16000),
    ])
    p = res.positions["AAA"]
    assert p.qty == 4
    assert p.avg_cost_usd == 17.5


def test_tc03_fee_folds_into_cost_basis():
    res = derive_positions([_row("2026-01-01", "AAA", "BUY", 2, 10, 16000, fee=4)])
    p = res.positions["AAA"]
    assert p.avg_cost_usd == 12  # (20 + 4) / 2


def test_tc04_partial_sell_realized_and_avg_unchanged():
    res = derive_positions([
        _row("2026-01-01", "AAA", "BUY", 1, 10, 16000),
        _row("2026-01-02", "AAA", "BUY", 3, 20, 16000),
        _row("2026-01-03", "AAA", "SELL", 2, 25, 16000),
    ])
    p = res.positions["AAA"]
    assert round(p.realized_usd, 6) == 15  # 2 * (25 - 17.5)
    assert p.qty == 2
    assert p.avg_cost_usd == 17.5


def test_tc05_full_sell_closes_position():
    res = derive_positions([
        _row("2026-01-01", "AAA", "BUY", 1, 10, 16000),
        _row("2026-01-02", "AAA", "SELL", 1, 12, 16000),
    ])
    p = res.positions["AAA"]
    assert p.qty == 0
    assert p.is_open is False
    assert "AAA" not in res.open_positions()
    assert round(p.realized_usd, 6) == 2


def test_tc06_unrealized_usd():
    res = derive_positions([_row("2026-01-01", "AAA", "BUY", 2, 10, 16000)])
    pnl = unrealized_pnl(res.positions["AAA"], current_price=9, usdidr_now=16000)
    assert pnl.unrealized_usd == -2


def test_tc07_currency_split_reconciles():
    res = derive_positions([_row("2026-01-01", "AAA", "BUY", 1, 100, 16000)])
    pnl = unrealized_pnl(res.positions["AAA"], current_price=100, usdidr_now=17000)
    assert round(pnl.asset_pnl_idr, 6) == 0
    assert round(pnl.fx_pnl_idr, 6) == 100000
    assert round(pnl.asset_pnl_idr + pnl.fx_pnl_idr, 6) == round(
        pnl.total_unrealized_idr, 6
    )


def test_tc08_date_order_independent():
    rows_chrono = [
        _row("2026-01-01", "AAA", "BUY", 1, 10, 16000),
        _row("2026-01-02", "AAA", "BUY", 3, 20, 16000),
    ]
    rows_reversed = list(reversed(rows_chrono))
    a = derive_positions(rows_chrono).positions["AAA"]
    b = derive_positions(rows_reversed).positions["AAA"]
    assert a.qty == b.qty
    assert a.avg_cost_usd == b.avg_cost_usd


def test_tc09_malformed_row_skipped_not_fatal():
    bad = _row("2026-01-02", "AAA", "BUY", 1, None, 16000)  # missing price
    res = derive_positions([
        _row("2026-01-01", "AAA", "BUY", 2, 10, 16000),
        bad,
    ])
    assert res.positions["AAA"].qty == 2  # valid row still processed
    assert len(res.skipped) == 1
    assert "price_usd" in res.skipped[0]["reason"]


def test_tc10_ticker_normalization():
    res = derive_positions([
        _row("2026-01-01", " smh ", "BUY", 1, 10, 16000),
        _row("2026-01-02", "SMH", "BUY", 1, 20, 16000),
    ])
    assert "SMH" in res.positions
    assert res.positions["SMH"].qty == 2


# --- IDR-native support (follow-up: RDPU / cash in rupiah) ----------------- #
def _idr_row(date, ticker, action, qty, price_idr, fee=0, note=""):
    return {
        "date": date, "ticker": ticker, "action": action, "quantity": qty,
        "price_usd": price_idr,  # for IDR rows this column carries the IDR price
        "fee_usd": fee, "currency": "IDR", "note": note,
    }


def test_idr_row_needs_no_usdidr():
    # usdidr omitted entirely; IDR currency makes it default to 1 (no conversion).
    res = derive_positions([_idr_row("2026-01-01", "RDPU", "BUY", 1, 2_002_079)])
    pos = res.positions["RDPU"]
    assert pos.currency == "IDR"
    assert pos.qty == 1
    assert pos.cost_basis_idr == 2_002_079  # price * qty * 1, no FX


def test_idr_position_has_zero_fx_pnl():
    res = derive_positions([_idr_row("2026-01-01", "RDPU", "BUY", 1, 2_000_000)])
    pnl = unrealized_pnl(res.positions["RDPU"], current_price=2_002_079, usdidr_now=17905)
    # IDR-native: current FX forced to 1 -> all P&L is asset, FX P&L exactly 0.
    assert round(pnl.fx_pnl_idr, 6) == 0.0
    assert round(pnl.market_value_idr, 6) == 2_002_079
    assert round(pnl.total_unrealized_idr, 6) == 2_079


def test_usd_row_still_requires_usdidr():
    bad = {
        "date": "2026-01-01", "ticker": "SMH", "action": "BUY",
        "quantity": 1, "price_usd": 600, "currency": "USD",  # no usdidr
    }
    res = derive_positions([bad])
    assert "SMH" not in res.positions
    assert res.skipped and "usdidr" in res.skipped[0]["reason"]


def test_default_currency_is_usd_backward_compatible():
    # A row with no 'currency' key behaves exactly as before (USD, needs usdidr).
    res = derive_positions([_row("2026-01-01", "AAA", "BUY", 2, 10, 16000)])
    assert res.positions["AAA"].currency == "USD"
    assert res.positions["AAA"].qty == 2
