"""FRED (Federal Reserve Economic Data) client.

Implements docs/01-data-sources/02. FRED (Macro).md.

Fetches the macro series the pipeline needs using only stdlib urllib (no extra
dependency, mirroring the predecessor's approach). Fail-safe: a failing series
yields a flagged, partial result and never crashes the run. The API key is
never emitted in logs (redaction helper provided and used in error text).
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request
from dataclasses import dataclass

_BASE = "https://api.stlouisfed.org/fred/series/observations"

# Series pulled (verified IDs). See the spec for the rationale of each.
SERIES = {
    "DGS10": "10-Year Treasury yield",
    "DGS2": "2-Year Treasury yield",
    "T10Y2Y": "10Y-2Y spread (yield curve)",
    "DFF": "Federal Funds Effective Rate",
    "DTWEXBGS": "Broad US Dollar Index",
    "VIXCLS": "CBOE VIX",
}


@dataclass
class SeriesObs:
    """Latest value plus ~1w/1m ago and the changes. Error flag if unavailable."""

    series_id: str
    latest: float | None = None
    latest_date: str | None = None
    week_ago: float | None = None
    month_ago: float | None = None
    change_1w: float | None = None
    change_1m: float | None = None
    error: str | None = None


def redact_key(text: str, key: str | None) -> str:
    """Replace the API key in any string (for safe logging/errors)."""
    if key:
        return text.replace(key, "***")
    return text


def _parse_observations(payload: dict) -> list[tuple[str, float]]:
    """Return [(date, value)] for valid observations; FRED uses '.' for missing."""
    out: list[tuple[str, float]] = []
    for obs in payload.get("observations", []):
        v = obs.get("value")
        if v in (None, ".", ""):
            continue
        try:
            out.append((obs.get("date", ""), float(v)))
        except (TypeError, ValueError):
            continue
    return out


def build_series(series_id: str, observations: list[tuple[str, float]]) -> SeriesObs:
    """Build a SeriesObs from parsed (date, value) observations (newest last)."""
    if not observations:
        return SeriesObs(series_id=series_id, error="no valid observations")
    dates = [d for d, _ in observations]
    vals = [v for _, v in observations]
    latest = vals[-1]
    # ~1 week = 5 business days, ~1 month = 21 business days.
    week_ago = vals[-6] if len(vals) >= 6 else None
    month_ago = vals[-22] if len(vals) >= 22 else None
    return SeriesObs(
        series_id=series_id,
        latest=latest,
        latest_date=dates[-1],
        week_ago=week_ago,
        month_ago=month_ago,
        change_1w=(latest - week_ago) if week_ago is not None else None,
        change_1m=(latest - month_ago) if month_ago is not None else None,
    )


def fetch_series(
    series_id: str, api_key: str, *, timeout: int = 15, _opener=None
) -> SeriesObs:
    """Fetch one FRED series. Fail-safe: returns a SeriesObs with .error set."""
    params = urllib.parse.urlencode({
        "series_id": series_id,
        "api_key": api_key,
        "file_type": "json",
        "sort_order": "asc",
        "limit": "400",
    })
    url = f"{_BASE}?{params}"
    try:
        opener = _opener or urllib.request.urlopen
        req = urllib.request.Request(url, headers={"User-Agent": "finance-portfolio"})
        with opener(req, timeout=timeout) as resp:
            payload = json.load(resp)
        return build_series(series_id, _parse_observations(payload))
    except Exception as exc:  # noqa: BLE001 - external fetch, stay fail-safe
        return SeriesObs(series_id=series_id, error=redact_key(str(exc), api_key))


def fetch_all(api_key: str, *, _opener=None) -> dict[str, SeriesObs]:
    """Fetch every configured series. Each failure is isolated."""
    return {sid: fetch_series(sid, api_key, _opener=_opener) for sid in SERIES}
