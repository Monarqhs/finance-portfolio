"""Thin Gemini API caller used by the narrative layer.

Returns a callable (prompt -> text) that narrative.generate_narrative injects.
Uses the free-tier REST endpoint via stdlib urllib (no SDK dependency). The key
is never logged. If anything is missing, the narrative layer falls back to the
deterministic summary.
"""
from __future__ import annotations

import json
import urllib.request

_ENDPOINT = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "gemini-2.0-flash:generateContent"
)


def build_gemini_call(api_key: str, *, timeout: int = 30, _opener=None):
    """Return a `prompt -> text` callable, or None if no key."""
    if not api_key:
        return None
    opener = _opener or urllib.request.urlopen

    def call(prompt: str) -> str:
        body = json.dumps({
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.2},
        }).encode()
        req = urllib.request.Request(
            f"{_ENDPOINT}?key={api_key}",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with opener(req, timeout=timeout) as resp:
            payload = json.load(resp)
        return payload["candidates"][0]["content"]["parts"][0]["text"]

    return call
