"""Thin Gemini API caller used by the narrative layer.

Returns a callable (prompt -> text) that narrative.generate_narrative injects.
Uses the free-tier REST endpoint via stdlib urllib (no SDK dependency). The key
is never logged. If anything is missing, the narrative layer falls back to the
deterministic summary.
"""
from __future__ import annotations

import json
import os
import urllib.request

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
    api_key: str, *, model: str | None = None, timeout: int = 30, _opener=None
):
    """Return a `prompt -> text` callable, or None if no key.

    The header auth header (X-goog-api-key) is used instead of a query param so
    the key never appears in a URL that could be logged.
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
        req = urllib.request.Request(
            endpoint,
            data=body,
            headers={
                "Content-Type": "application/json",
                "X-goog-api-key": api_key,
            },
            method="POST",
        )
        with opener(req, timeout=timeout) as resp:
            payload = json.load(resp)
        return payload["candidates"][0]["content"]["parts"][0]["text"]

    return call
