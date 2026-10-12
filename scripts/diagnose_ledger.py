"""Diagnose what the pipeline actually reads from your Google Sheet.

Run on your own machine to see, WITHOUT sending any email, exactly what the
ledger reader gets from the sheet and how it is interpreted. This makes an empty
report explainable (bad range name, locale-mangled quantities, permission, ...).

Usage (set the same values your GitHub Secrets use):
    pip install -r requirements.txt
    export SHEET_ID="your-sheet-id"
    export GOOGLE_SA_JSON="$(cat your-service-account.json)"
    python scripts/diagnose_ledger.py

It prints the raw grid, the parsed transactions, any skipped rows with reasons,
and the derived open positions. No amounts are sent anywhere.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from analyst.ledger import derive_positions  # noqa: E402
from analyst.sources.sheet import build_google_fetcher, rows_to_transactions  # noqa: E402


def main() -> int:
    sheet_id = os.environ.get("SHEET_ID", "")
    sa_json = os.environ.get("GOOGLE_SA_JSON", "")
    if not sheet_id or not sa_json:
        print("Set SHEET_ID and GOOGLE_SA_JSON environment variables first.")
        return 1

    print(f"Sheet ID: {sheet_id[:6]}... (len {len(sheet_id)})")
    try:
        fetcher = build_google_fetcher(sheet_id, json.loads(sa_json))
        grid = fetcher()
    except Exception as exc:  # noqa: BLE001
        print(f"\nFAILED to read the sheet: {exc}")
        print(
            "\nCommon causes:\n"
            "  - The worksheet is not named 'transactions' (range is "
            "'transactions!A:H').\n"
            "  - The sheet is not shared with the service account email "
            "(client_email in the JSON) as Viewer.\n"
            "  - Google Sheets API not enabled on the project.\n"
            "  - SHEET_ID is wrong."
        )
        return 1

    print(f"\nRaw grid: {len(grid)} row(s)")
    for i, row in enumerate(grid[:8]):
        print(f"  row {i}: {row}")

    txns = rows_to_transactions(grid)
    print(f"\nParsed transactions: {len(txns)}")
    for t in txns:
        print(f"  {t}")

    result = derive_positions(txns)
    if result.skipped:
        print(f"\nSkipped rows: {len(result.skipped)}")
        for s in result.skipped:
            print(f"  reason: {s['reason']}  <- {s['row']}")
    else:
        print("\nSkipped rows: none")

    print("\nDerived positions:")
    for ticker, p in result.positions.items():
        status = "OPEN" if p.is_open else "closed"
        print(f"  {ticker:6} qty={p.qty} avg_cost={p.avg_cost_usd} {p.currency} [{status}]")

    opens = result.open_positions()
    print(f"\n=> {len(opens)} open position(s): {', '.join(opens) or 'NONE'}")
    if not opens:
        print(
            "\nIf this says NONE but you have rows, the usual culprit is "
            "quantities read as 0 due to spreadsheet locale (comma vs dot "
            "decimal). Open each quantity cell and confirm the real value in the "
            "formula bar is a small decimal (e.g. 0.308324219), not 0."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
