"""Send the digest via the Gmail API (OAuth, gmail.send scope only).

Adapted from the predecessor. Headless by design for GitHub Actions: the token
is read from the GMAIL_TOKEN_JSON env var (a GitHub Secret). The Google client
is imported lazily so unit tests and preview runs need no Google dependency.
"""
from __future__ import annotations

import base64
import json
import os
from email.mime.text import MIMEText

SCOPES = ["https://www.googleapis.com/auth/gmail.send"]


def _service():
    """Build an authenticated Gmail service from GMAIL_TOKEN_JSON (headless)."""
    from google.auth.transport.requests import Request  # type: ignore
    from google.oauth2.credentials import Credentials  # type: ignore
    from googleapiclient.discovery import build  # type: ignore

    token = os.environ.get("GMAIL_TOKEN_JSON")
    if not token:
        raise RuntimeError("GMAIL_TOKEN_JSON is not set")
    creds = Credentials.from_authorized_user_info(json.loads(token), SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
    return build("gmail", "v1", credentials=creds)


def send_email(subject: str, html_body: str, to: str) -> tuple[bool, str]:
    """Send one HTML email. Returns (ok, message). Never raises (fail-safe)."""
    if not to:
        return False, "recipient (EMAIL_TO) is empty"
    try:
        service = _service()
        msg = MIMEText(html_body, "html", "utf-8")
        msg["To"] = to
        msg["Subject"] = subject
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        sent = service.users().messages().send(userId="me", body={"raw": raw}).execute()
        return True, f"sent to {to} (id={sent.get('id')})"
    except Exception as exc:  # noqa: BLE001 - stay fail-safe
        return False, f"send failed: {exc}"
