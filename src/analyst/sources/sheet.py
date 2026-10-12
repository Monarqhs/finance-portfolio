"""Google Sheet ledger reader.

Implements the read side of docs/01-data-sources/01. Ledger (Google Sheet).md.

The transport (Google Sheets API client) is injected, so the parsing/normalizing
logic is fully unit-testable offline. In production the caller passes a function
that returns the raw grid (list of rows) read read-only via a service account.

Only the parsing is here; derivation (positions, P&L) lives in analyst.ledger.
"""
from __future__ import annotations

from typing import Callable

# Expected header, in order. Matching is case-insensitive and tolerant of extra
# trailing columns.
HEADER = [
    "date", "ticker", "action", "quantity", "price_usd", "fee_usd", "usdidr",
    "note", "currency",
]


def rows_to_transactions(grid: list[list]) -> list[dict]:
    """Turn a raw sheet grid (row 1 = header) into transaction dicts.

    Columns are matched by header name, so column order in the sheet may vary as
    long as the names match. Unknown/missing columns are tolerated; the ledger's
    own validation (analyst.ledger) decides what is usable.
    """
    if not grid:
        return []
    header = [str(h).strip().lower() for h in grid[0]]
    index = {name: header.index(name) for name in HEADER if name in header}

    txns: list[dict] = []
    for raw in grid[1:]:
        if not raw or all((c is None or str(c).strip() == "") for c in raw):
            continue  # skip blank trailing rows

        def cell(name: str):
            i = index.get(name)
            if i is None or i >= len(raw):
                return None
            v = raw[i]
            return None if (v is None or str(v).strip() == "") else v

        txns.append({
            "date": cell("date"),
            "ticker": cell("ticker"),
            "action": cell("action"),
            "quantity": cell("quantity"),
            "price_usd": cell("price_usd"),
            "fee_usd": cell("fee_usd"),
            "usdidr": cell("usdidr"),
            "note": cell("note"),
            "currency": cell("currency"),
        })
    return txns


def read_ledger(fetch_grid: Callable[[], list[list]]) -> list[dict]:
    """Read and parse the ledger via an injected grid fetcher. Fail-safe: an
    unreachable sheet raises in the fetcher; callers decide how to degrade."""
    grid = fetch_grid()
    return rows_to_transactions(grid)


def build_google_fetcher(sheet_id: str, sa_info: dict, range_: str = "transactions!A:I"):
    """Build a grid fetcher backed by the Google Sheets API (read-only).

    Imported lazily so the Google client is only needed in production, not for
    tests or for runs that don't touch the sheet.
    """
    from google.oauth2.service_account import Credentials  # type: ignore
    from googleapiclient.discovery import build  # type: ignore

    scopes = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
    creds = Credentials.from_service_account_info(sa_info, scopes=scopes)
    service = build("sheets", "v4", credentials=creds, cache_discovery=False)

    def fetch_grid() -> list[list]:
        resp = (
            service.spreadsheets()
            .values()
            .get(spreadsheetId=sheet_id, range=range_)
            .execute()
        )
        return resp.get("values", [])

    return fetch_grid
