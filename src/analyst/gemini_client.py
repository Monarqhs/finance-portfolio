"""Thin Gemini API caller used by the narrative layer.

Returns a callable (prompt -> text) that narrative.generate_narrative injects.
Uses the free-tier REST endpoint via stdlib urllib (no SDK dependency). The key
is never logged. If anything is missing, the narrative layer falls back to the
deterministic summary.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

# HTTP statuses worth retrying: transient server/overload/rate-limit responses.
# 503 ("model experiencing high demand") is common on the free tier.
_RETRYABLE = {429, 500, 503}

# Model is configurable via GEMINI_MODEL. Default is the "latest flash" alias so
# the pipeline keeps working as Google rotates concrete version names (the old
# hardcoded gemini-2.0-flash could 404 and silently force the deterministic
# fallback).
DEFAULT_MODEL = "gemini-flash-latest"
_ENDPOINT_TMPL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "{model}:generateContent"
)


def build_gemini_call(
    api_key: str,
    *,
    model: str | None = None,
    timeout: int = 30,
    retries: int = 3,
    backoff: float = 2.0,
    _opener=None,
    _sleep=time.sleep,
):
    """Return a `prompt -> text` callable, or None if no key.

    The API key is sent in the X-goog-api-key header (never in the URL, so it
    cannot leak into a logged URL). Transient failures (HTTP 429/500/503 -- e.g.
    "model experiencing high demand") are retried with exponential backoff
    before giving up; non-retryable errors (bad key, 404) raise immediately so
    the narrative layer falls back deterministically.
    """
    if not api_key:
        return None
    model = model or os.environ.get("GEMINI_MODEL") or DEFAULT_MODEL
    endpoint = _ENDPOINT_TMPL.format(model=model)
    opener = _opener or urllib.request.urlopen

    def call(prompt: str) -> str:
        body = json.dumps({
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.2},
        }).encode()
        last_exc: Exception | None = None
        for attempt in range(retries):
            req = urllib.request.Request(
                endpoint,
                data=body,
                headers={
                    "Content-Type": "application/json",
                    "X-goog-api-key": api_key,
                },
                method="POST",
            )
            try:
                with opener(req, timeout=timeout) as resp:
                    payload = json.load(resp)
                return payload["candidates"][0]["content"]["parts"][0]["text"]
            except urllib.error.HTTPError as exc:
                last_exc = exc
                if exc.code in _RETRYABLE and attempt < retries - 1:
                    wait = backoff * (2 ** attempt)
                    print(f"[gemini] {exc.code} transient; retry in {wait:.0f}s")
                    _sleep(wait)
                    continue
                raise  # non-retryable, or out of attempts
        if last_exc:
            raise last_exc
        raise RuntimeError("gemini call made no attempts")

    return call
