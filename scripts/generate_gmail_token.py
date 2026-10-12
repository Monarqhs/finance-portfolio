"""One-time helper to generate token.json for the Gmail send flow.

Run this ONCE on your own computer (it opens a browser to log in). It reads
credentials.json (the OAuth Desktop client you downloaded) and writes
token.json. The full contents of token.json then become the GitHub Secret
GMAIL_TOKEN_JSON.

Usage:
    pip install google-auth-oauthlib
    python scripts/generate_gmail_token.py

Notes:
- credentials.json must be in the current directory (same folder you run from).
- Scope is gmail.send only (can send mail, cannot read your inbox).
- Neither credentials.json nor token.json is ever committed (see .gitignore).
- If your OAuth consent screen is in "Testing" mode, Google revokes the refresh
  token every 7 days. To make it permanent, publish the app
  (OAuth consent screen / Audience -> Publish app). Scope is minimal, so no
  Google verification is normally required.
"""
from __future__ import annotations

import os
import sys

SCOPES = ["https://www.googleapis.com/auth/gmail.send"]
CREDENTIALS = "credentials.json"
TOKEN = "token.json"


def main() -> int:
    if not os.path.exists(CREDENTIALS):
        print(
            f"ERROR: {CREDENTIALS} not found in {os.getcwd()}.\n"
            "Download it from Google Cloud Console "
            "(APIs & Services -> Credentials -> OAuth client ID -> Desktop app)."
        )
        return 1

    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        print(
            "ERROR: dependency missing. Install it with:\n"
            "  pip install google-auth-oauthlib"
        )
        return 1

    flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS, SCOPES)
    # Opens a local browser window for you to log in and approve.
    creds = flow.run_local_server(port=0)

    with open(TOKEN, "w", encoding="utf-8") as fh:
        fh.write(creds.to_json())

    print(
        f"\nSuccess. Wrote {TOKEN}.\n\n"
        "Next steps:\n"
        f"  1. Open {TOKEN} and copy its ENTIRE contents.\n"
        "  2. In your GitHub repo: Settings -> Secrets and variables -> Actions\n"
        "     -> New repository secret -> name it GMAIL_TOKEN_JSON -> paste.\n"
        "  3. Do NOT paste credentials.json; the secret must be token.json\n"
        "     (the one containing a top-level \"refresh_token\")."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
