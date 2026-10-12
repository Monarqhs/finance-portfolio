"""Tests for the Yahoo price fetcher (stdlib-only, fail-safe)."""
import io
import json

from analyst.sources import yahoo


def _chart_payload(closes):
    return {"chart": {"result": [{"indicators": {"quote": [{"close": closes}]}}]}}


def _opener(payload):
    class _Ctx:
        def __enter__(self_):
            return io.BytesIO(json.dumps(payload).encode())

        def __exit__(self_, *a):
            return False

    return lambda req, timeout=0: _Ctx()


def test_symbol_mapping():
    assert yahoo.yahoo_symbol("GC=F") == "GC%3DF"
    assert yahoo.yahoo_symbol("SMH") == "SMH"


def test_fetch_closes_parses_series():
    closes = yahoo.fetch_closes("SMH", _opener=_opener(_chart_payload([1.0, None, 2.0])))
    assert closes == [1.0, 2.0]  # None dropped


def test_fetch_closes_failsafe_empty():
    def boom(req, timeout=0):
        raise OSError("blocked")

    assert yahoo.fetch_closes("SMH", _opener=boom) == []


def test_fetch_usdidr():
    assert yahoo.fetch_usdidr(_opener=_opener(_chart_payload([16000.0, 17000.0]))) == 17000.0
