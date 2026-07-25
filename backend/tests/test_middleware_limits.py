"""Request-limit middleware — body-size guard + rate-limit fallback."""
from starlette.requests import Request
from starlette.responses import Response

from app.core.middleware import BodySizeLimitMiddleware, RateLimitMiddleware



def _req(headers: list[tuple[bytes, bytes]], path="/x") -> Request:
    return Request({"type": "http", "method": "POST", "path": path,
                    "headers": headers, "query_string": b"", "client": ("1.2.3.4", 5)})


async def _ok(_req):
    return Response("ok")


async def test_body_size_limit_rejects_oversized():
    mw = BodySizeLimitMiddleware(app=None, max_bytes=100)
    resp = await mw.dispatch(_req([(b"content-length", b"101")]), _ok)
    assert resp.status_code == 413


async def test_body_size_limit_allows_within_limit():
    mw = BodySizeLimitMiddleware(app=None, max_bytes=100)
    resp = await mw.dispatch(_req([(b"content-length", b"100")]), _ok)
    assert resp.status_code == 200


async def test_body_size_limit_ignores_missing_or_bad_header():
    mw = BodySizeLimitMiddleware(app=None, max_bytes=100)
    assert (await mw.dispatch(_req([]), _ok)).status_code == 200
    assert (await mw.dispatch(_req([(b"content-length", b"abc")]), _ok)).status_code == 200


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
