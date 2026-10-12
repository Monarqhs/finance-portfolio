"""Smoke test for the pipeline orchestrator in preview mode.

Verifies the whole pipeline composes and renders without network or secrets:
all external sources are monkeypatched, and --preview writes a file (no send).
"""
import os

from analyst import main as pipeline


def _price_series(n=260, start=100.0, step=1.0):
    return [start + i * step for i in range(n)]


def test_preview_pipeline_renders(monkeypatch, tmp_path):
    # No ledger (Sheet) configured -> ledger section degrades gracefully, but we
    # still inject a couple of transactions by patching read_ledger.
    monkeypatch.setattr(pipeline, "build_google_fetcher", lambda *a, **k: (lambda: []))
    monkeypatch.setattr(
        pipeline, "read_ledger",
        lambda fetcher: [
            {"date": "2026-09-15", "ticker": "SMH", "action": "BUY",
             "quantity": "0.3", "price_usd": "10000", "fee_usd": "0", "usdidr": "17000"},
            {"date": "2026-09-29", "ticker": "MU", "action": "BUY",
             "quantity": "0.05", "price_usd": "18000", "fee_usd": "0", "usdidr": "17300"},
        ],
    )
    # Prices + FX (deterministic, no network).
    monkeypatch.setattr(
        pipeline.yahoo, "fetch_prices",
        lambda tickers, **k: {t: _price_series() for t in tickers},
    )
    monkeypatch.setattr(pipeline.yahoo, "fetch_usdidr", lambda **k: 17500.0)
    monkeypatch.setattr(pipeline.yahoo, "fetch_closes", lambda t, **k: [17000.0] * 10)
    # FRED (empty -> macro degrades to few/no tags, still fine).
    monkeypatch.setattr(pipeline.fred, "fetch_all", lambda key: {})

    monkeypatch.chdir(tmp_path)
    html = pipeline.run(preview=True)

    assert "<html>" in html
    assert "Weekly Portfolio Analyst" in html
    assert "Positions" in html
    assert (tmp_path / "preview.html").exists()


def test_preview_does_not_send(monkeypatch, tmp_path):
    # If any send were attempted it would import gmail_sender; assert the
    # preview path writes a file and returns, with no EMAIL_TO needed.
    monkeypatch.setattr(pipeline, "build_google_fetcher", lambda *a, **k: (lambda: []))
    monkeypatch.setattr(pipeline, "read_ledger", lambda fetcher: [])
    monkeypatch.setattr(pipeline.yahoo, "fetch_prices", lambda tickers, **k: {})
    monkeypatch.setattr(pipeline.yahoo, "fetch_usdidr", lambda **k: None)
    monkeypatch.setattr(pipeline.yahoo, "fetch_closes", lambda t, **k: [])
    monkeypatch.setattr(pipeline.fred, "fetch_all", lambda key: {})

    monkeypatch.chdir(tmp_path)
    html = pipeline.run(preview=True)
    assert (tmp_path / "preview.html").exists()
    assert "<html>" in html
