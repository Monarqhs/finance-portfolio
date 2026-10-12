"""Tests for the Gemini client (offline, mocked transport)."""
import io
import json

from analyst.gemini_client import build_gemini_call


def test_no_key_returns_none():
    assert build_gemini_call("") is None


def test_call_parses_text():
    payload = {"candidates": [{"content": {"parts": [{"text": "hello"}]}}]}

    class _Ctx:
        def __enter__(self_):
            return io.BytesIO(json.dumps(payload).encode())

        def __exit__(self_, *a):
            return False

    call = build_gemini_call("KEY", _opener=lambda req, timeout=0: _Ctx())
    assert call("prompt") == "hello"
