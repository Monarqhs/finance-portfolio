"""Tests for the FRED client.

Covers docs/01-data-sources/02. FRED (Macro).md numbered Test cases 1:1
(TC-01 .. TC-05). Uses recorded fixture payloads / fake openers, no live net.
"""
import io
import json

from analyst.sources import fred


def _payload(pairs):
    return {"observations": [{"date": d, "value": v} for d, v in pairs]}


def _fake_opener(payload):
    class _Ctx:
        def __enter__(self_):
            return io.BytesIO(json.dumps(payload).encode())

        def __exit__(self_, *a):
            return False

    def opener(req, timeout=0):
        return _Ctx()

    return opener


def test_tc01_parse_latest_observation():
    pairs = [("2026-01-01", "4.10"), ("2026-01-02", "4.25")]
    obs = fred.fetch_series("DGS10", "KEY", _opener=_fake_opener(_payload(pairs)))
    assert obs.latest == 4.25
    assert obs.latest_date == "2026-01-02"


def test_tc02_missing_dot_observation_skipped():
    pairs = [("2026-01-01", "4.10"), ("2026-01-02", "."), ("2026-01-03", "4.30")]
    obs = fred.fetch_series("DGS10", "KEY", _opener=_fake_opener(_payload(pairs)))
    assert obs.latest == 4.30  # the '.' row is skipped


def test_tc03_week_month_deltas():
    # 25 ascending points so both 1w (5) and 1m (21) look-backs exist.
    pairs = [(f"2026-02-{i:02d}", f"{1.00 + i*0.01:.2f}") for i in range(1, 26)]
    obs = fred.fetch_series("DGS10", "KEY", _opener=_fake_opener(_payload(pairs)))
    vals = [1.00 + i * 0.01 for i in range(1, 26)]
    assert abs(obs.change_1w - (vals[-1] - vals[-6])) < 1e-9
    assert abs(obs.change_1m - (vals[-1] - vals[-22])) < 1e-9


def test_tc04_failed_series_flagged_not_fatal():
    def boom(req, timeout=0):
        raise OSError("network down")

    obs = fred.fetch_series("DGS10", "KEY", _opener=boom)
    assert obs.error is not None
    assert obs.latest is None


def test_tc05_api_key_redacted_in_error():
    def boom(req, timeout=0):
        raise OSError("failed for api_key=SECRET123")

    obs = fred.fetch_series("DGS10", "SECRET123", _opener=boom)
    assert "SECRET123" not in (obs.error or "")
    assert "***" in (obs.error or "")
