"""Runtime configuration (no secrets committed; all sensitive values via env).

Portfolio holdings here are only the ticker universe to price and classify; the
real positions come from the owner's Google Sheet ledger at runtime.
"""
from __future__ import annotations

import os

# Tickers to price (holdings + benchmarks + opportunity watchlist handled in
# their own module). Benchmarks used for relative return.
BENCHMARKS = ["SMH", "VOO"]

# Opportunity watchlist is defined in analyst.opportunity.DEFAULT_WATCHLIST.

# Secrets / environment (never hard-coded).
EMAIL_TO = os.environ.get("EMAIL_TO", "")
SHEET_ID = os.environ.get("SHEET_ID", "")
GOOGLE_SA_JSON = os.environ.get("GOOGLE_SA_JSON", "")
FRED_API_KEY = os.environ.get("FRED_API_KEY", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

EMAIL_SUBJECT_PREFIX = "📊 Weekly Portfolio Analyst"
