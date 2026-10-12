"""Yahoo Finance price fetcher.

Carried over from the predecessor (finance-weekly-report): the stable JSON chart
endpoint, stdlib urllib only, with a query2 fallback and fail-safe behavior.
Used for prices, technicals, and USD/IDR. Not relied upon for fundamentals.
"""
from __future__ import annotations

import json
import urllib.request

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
_HOSTS = ("query1.finance.yahoo.com", "query2.finance.yahoo.com")

# Symbol remaps where the Yahoo symbol needs URL-encoding or differs.
_SYMBOL_MAP = {
    "GC=F": "GC%3DF",   # gold futures
    "IDR=X": "IDR%3DX",  # USD/IDR
}


def yahoo_symbol(ticker: str) -> str:
    return _SYMBOL_MAP.get(ticker, ticker)


def fetch_closes(ticker: str, *, range_: str = "1y", timeout: int = 15, _opener=None) -> list[float]:
    """Daily closes (~1y), oldest first. Returns [] if all hosts fail (fail-safe)."""
    symbol = yahoo_symbol(ticker)
    opener = _opener or urllib.request.urlopen
    for host in _HOSTS:
        url = f"https://{host}/v8/finance/chart/{symbol}?range={range_}&interval=1d"
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": _UA, "Accept": "application/json"}
            )
            with opener(req, timeout=timeout) as resp:
                data = json.load(resp)
            result = data.get("chart", {}).get("result")
            if not result:
                continue
            quote = result[0].get("indicators", {}).get("quote", [{}])[0]
            closes = [float(c) for c in quote.get("close", []) if c is not None]
            if closes:
                return closes
        except Exception:  # noqa: BLE001 - try next host, stay fail-safe
            continue
    return []


def fetch_prices(tickers: list[str], *, _opener=None) -> dict[str, list[float]]:
    """Fetch close series for several tickers; failures yield an empty list."""
    return {t: fetch_closes(t, _opener=_opener) for t in tickers if t}


def fetch_usdidr(*, _opener=None) -> float | None:
    """Latest USD/IDR, or None if unavailable."""
    closes = fetch_closes("IDR=X", _opener=_opener)
    return closes[-1] if closes else None
