# finance-portfolio

A personal investment **analyst** that emails a weekly portfolio report. It
knows your real positions (from your own Google Sheet), reads the market and the
macro backdrop, flags concentration risk, surfaces sector-ETF diversification
ideas, and writes an evidence-first analyst note — all on free tiers.

This is the upgrade of a price **tracker** into an **analyst**. See
[`docs/`](docs/) for the full contract-first design.

## What it does

Every week a GitHub Actions job runs the pipeline and emails you a report with:

1. **Positions & P&L** — from your transaction ledger, including the
   **USD/IDR currency effect** (asset vs FX P&L).
2. **Portfolio risk** — sector/single-factor concentration (with ETF
   look-through), HHI, volatility, correlation, relative return.
3. **Macro & currency** — Treasury yields, the yield curve, Fed stance, the
   dollar, VIX, and USD/IDR, turned into regime tags linked to your exposure.
4. **Opportunities** — sector ETFs scored for healthy trend and **low
   correlation to semiconductors**, to counter concentration.
5. **Signals** — per-holding technical condition labels.
6. **Analyst note** — an optional LLM narrative (Gemini free tier) bounded by
   hard guardrails; a deterministic summary if the LLM is off.

Design principles: **evidence-first** (every claim carries its evidence and
limitation), **no price prediction**, **fail-safe** (a failed source degrades to
a note; the email still ships), and **privacy** (your real amounts never leave
your systems toward any third party).

## Architecture

```
GitHub Actions (weekly) -> fetch (Sheet, Yahoo, FRED) -> analyze -> narrate (Gemini, optional)
                        -> render HTML -> send (Gmail)
```

- Core analysis is **stdlib-only** Python; Google client only for Gmail/Sheets.
- See [`docs/00-overview/02. Architecture.md`](docs/00-overview/02.%20Architecture.md).

## Project layout

```
src/analyst/
  signal_engine.py   technical primitives + signal ladder
  ledger.py          positions, P&L, currency split (from transactions)
  risk.py            concentration & risk metrics
  macro.py           FRED regime tags + non-forecast AI-bubble context
  opportunity.py     sector-ETF diversification scanner
  narrative.py       Gemini narrative with privacy + guardrails
  digest.py          weekly HTML email composition
  gmail_sender.py    send via Gmail API (headless)
  gemini_client.py   Gemini REST caller
  main.py            pipeline orchestrator (--preview to render only)
  sources/           yahoo.py, fred.py, sheet.py
tests/               84 tests, covering each spec's numbered Test cases
docs/                contract-first specs
```

## Local preview

Render the email to a file without sending (no secrets needed for the layout):

```bash
pip install -e ".[dev]"
python -m analyst.main --preview   # writes preview.html
```

## Setup

See [`docs/04-setup/01. Setup Guide.md`](docs/04-setup/01.%20Setup%20Guide.md)
for the Google Sheet schema, the service account, and every GitHub Secret.

## Tests

```bash
pip install -e ".[dev]"
pytest        # 84 tests
```

## Disclaimer

Informational only; not financial advice. The report describes current
conditions and never predicts prices.
