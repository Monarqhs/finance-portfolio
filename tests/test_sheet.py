"""Tests for the Google Sheet ledger reader (parsing side, offline)."""
from analyst.sources.sheet import read_ledger, rows_to_transactions


def test_parses_grid_by_header_name():
    grid = [
        ["date", "ticker", "action", "quantity", "price_usd", "fee_usd", "usdidr", "note"],
        ["2026-09-15", "SMH", "BUY", "0.308", "10983.87", "0", "17200", "tranche 1"],
    ]
    txns = rows_to_transactions(grid)
    assert len(txns) == 1
    assert txns[0]["ticker"] == "SMH"
    assert txns[0]["quantity"] == "0.308"
    assert txns[0]["usdidr"] == "17200"


def test_column_order_independent():
    grid = [
        ["ticker", "date", "action", "usdidr", "quantity", "price_usd"],
        ["MU", "2026-09-29", "BUY", "17350", "0.05", "18800"],
    ]
    txns = rows_to_transactions(grid)
    assert txns[0]["ticker"] == "MU"
    assert txns[0]["usdidr"] == "17350"
    assert txns[0]["fee_usd"] is None  # missing column tolerated


def test_blank_rows_skipped():
    grid = [
        ["date", "ticker", "action", "quantity", "price_usd", "usdidr"],
        ["2026-09-15", "SMH", "BUY", "1", "10", "17000"],
        ["", "", "", "", "", ""],
        [None, None, None, None, None, None],
    ]
    assert len(rows_to_transactions(grid)) == 1


def test_read_ledger_uses_injected_fetcher():
    grid = [
        ["date", "ticker", "action", "quantity", "price_usd", "usdidr"],
        ["2026-01-01", "AAA", "BUY", "2", "10", "16000"],
    ]
    txns = read_ledger(lambda: grid)
    assert txns[0]["ticker"] == "AAA"


def test_empty_grid():
    assert rows_to_transactions([]) == []


def test_currency_column_is_read():
    # The currency column (for IDR-native rows like RDPU) must be parsed.
    grid = [
        ["date", "ticker", "action", "quantity", "price_usd", "fee_usd", "usdidr", "note", "currency"],
        ["2026-10-06", "RDPU", "BUY", "1", "2002079", "0", "", "cash", "IDR"],
    ]
    txns = rows_to_transactions(grid)
    assert txns[0]["currency"] == "IDR"
    assert txns[0]["usdidr"] is None  # blank, allowed for IDR rows
