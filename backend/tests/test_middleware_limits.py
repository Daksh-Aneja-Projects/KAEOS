"""Request-limit middleware — body-size guard + rate-limit fallback."""
from starlette.requests import Request
from starlette.responses import Response

from app.core.middleware import (
    BodySizeLimitMiddleware,
    RateLimitMiddleware,
    SecurityHeadersMiddleware,
)



def _req(headers: list[tuple[bytes, bytes]], path="/x") -> Request:
    return Request({"type": "http", "method": "POST", "path": path,
                    "headers": headers, "query_string": b"", "client": ("1.2.3.4", 5)})


async def _ok(_req):
    return Response("ok")


async def _ok_asgi(scope, receive, send):
    await Response("ok")(scope, receive, send)


async def _run(mw, headers, path="/x") -> Response:
    """Drive a pure-ASGI middleware (BodySizeLimit, SecurityHeaders) and rebuild
    what it sent as a Response, so the assertions below stay response-shaped."""
    start = {}

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        if message["type"] == "http.response.start":
            start.update(message)

    await mw(_req(headers, path).scope, receive, send)
    return Response(status_code=start["status"],
                    headers={k.decode("latin-1"): v.decode("latin-1") for k, v in start["headers"]})


async def test_body_size_limit_rejects_oversized():
    mw = BodySizeLimitMiddleware(app=_ok_asgi, max_bytes=100)
    resp = await _run(mw, [(b"content-length", b"101")])
    assert resp.status_code == 413


async def test_body_size_limit_allows_within_limit():
    mw = BodySizeLimitMiddleware(app=_ok_asgi, max_bytes=100)
    resp = await _run(mw, [(b"content-length", b"100")])
    assert resp.status_code == 200


async def test_body_size_limit_ignores_missing_or_bad_header():
    mw = BodySizeLimitMiddleware(app=_ok_asgi, max_bytes=100)
    assert (await _run(mw, [])).status_code == 200
    assert (await _run(mw, [(b"content-length", b"abc")])).status_code == 200


async def test_rate_limit_memory_fallback_blocks_after_limit(monkeypatch):
    # Force the in-memory path (no Redis) and a tiny limit.
    mw = RateLimitMiddleware(app=None, requests_per_minute=3)

    async def _no_redis(caller_id, now):
        return None
    monkeypatch.setattr(mw, "_redis_exceeded", _no_redis)

    ok = 0
    limited = 0
    for _ in range(5):
        resp = await mw.dispatch(_req([], path="/api/v1/rules"), _ok)
        if resp.status_code == 429:
            limited += 1
        else:
            ok += 1
    assert ok == 3 and limited == 2   # first 3 pass, rest throttled


async def test_rate_limit_exempt_paths_never_throttled(monkeypatch):
    mw = RateLimitMiddleware(app=None, requests_per_minute=1)
    for _ in range(10):
        resp = await mw.dispatch(_req([], path="/health"), _ok)
        assert resp.status_code == 200


async def test_security_headers_present():
    mw = SecurityHeadersMiddleware(app=_ok_asgi)
    resp = await _run(mw, [])
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    assert resp.headers["X-Frame-Options"] == "DENY"
    assert resp.headers["Referrer-Policy"] == "no-referrer"
    csp = resp.headers["Content-Security-Policy"]
    assert "default-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp
    assert "script-src 'self'" in csp
    assert "object-src 'none'" in csp
    assert "font-src 'self' https://fonts.gstatic.com" in csp
    # connect-src MUST be present and reach the cross-origin API + WebSocket,
    # else the SPA (served on a different port) can make no XHR/WS calls at all.
    assert "connect-src" in csp
    assert "wss:" in csp and "ws://localhost:*" in csp
