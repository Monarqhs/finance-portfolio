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


def test_key_sent_in_header_not_url():
    captured = {}

    class _Ctx:
        def __enter__(self_):
            return io.BytesIO(json.dumps(
                {"candidates": [{"content": {"parts": [{"text": "ok"}]}}]}
            ).encode())

        def __exit__(self_, *a):
            return False

    def opener(req, timeout=0):
        captured["url"] = req.full_url
        captured["headers"] = req.headers
        return _Ctx()

    call = build_gemini_call("SECRET", model="gemini-flash-latest", _opener=opener)
    call("prompt")
    # Key must be in the header, never in the URL (which could be logged).
    assert "SECRET" not in captured["url"]
    assert captured["headers"].get("X-goog-api-key") == "SECRET"
    assert "gemini-flash-latest" in captured["url"]


def test_retries_on_503_then_succeeds():
    import urllib.error

    calls = {"n": 0}

    class _Ctx:
        def __enter__(self_):
            return io.BytesIO(json.dumps(
                {"candidates": [{"content": {"parts": [{"text": "recovered"}]}}]}
            ).encode())

        def __exit__(self_, *a):
            return False

    def opener(req, timeout=0):
        calls["n"] += 1
        if calls["n"] == 1:
            raise urllib.error.HTTPError(req.full_url, 503, "busy", {}, None)
        return _Ctx()

    slept = []
    call = build_gemini_call(
        "K", retries=3, backoff=0.0, _opener=opener, _sleep=lambda s: slept.append(s)
    )
    assert call("p") == "recovered"
    assert calls["n"] == 2  # first 503, then success


def test_non_retryable_error_raises():
    import urllib.error

    def opener(req, timeout=0):
        raise urllib.error.HTTPError(req.full_url, 401, "bad key", {}, None)

    call = build_gemini_call("K", retries=3, backoff=0.0, _opener=opener, _sleep=lambda s: None)
    try:
        call("p")
        assert False, "should have raised"
    except urllib.error.HTTPError as exc:
        assert exc.code == 401  # bad key is not retried


def test_gives_up_after_retries():
    import urllib.error

    attempts = {"n": 0}

    def opener(req, timeout=0):
        attempts["n"] += 1
        raise urllib.error.HTTPError(req.full_url, 503, "busy", {}, None)

    call = build_gemini_call("K", retries=3, backoff=0.0, _opener=opener, _sleep=lambda s: None)
    try:
        call("p")
        assert False, "should have raised after exhausting retries"
    except urllib.error.HTTPError as exc:
        assert exc.code == 503
    assert attempts["n"] == 3  # all retries used


def test_model_defaults_and_override(monkeypatch):
    from analyst.gemini_client import DEFAULT_MODEL

    captured = {}

    class _Ctx:
        def __enter__(self_):
            return io.BytesIO(json.dumps(
                {"candidates": [{"content": {"parts": [{"text": "ok"}]}}]}
            ).encode())

        def __exit__(self_, *a):
            return False

    def opener(req, timeout=0):
        captured["url"] = req.full_url
        return _Ctx()

    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    build_gemini_call("K", _opener=opener)("p")
    assert DEFAULT_MODEL in captured["url"]

    monkeypatch.setenv("GEMINI_MODEL", "gemini-2.5-pro")
    build_gemini_call("K", _opener=opener)("p")
    assert "gemini-2.5-pro" in captured["url"]
