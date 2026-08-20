"""S5.3.9 / S5.6.9 — the header-only middlewares are pure ASGI, and the
in-memory rate-limit windows do not grow without bound.

RequestId / BodySizeLimit / SecurityHeaders were BaseHTTPMiddleware, which costs
an anyio task group plus two tasks plus a stream pair on every request. They are
plain ASGI callables now, so these tests pin the observable behaviour that must
not have changed: the same headers, the same 413 body, the same request.state.
"""
import re

import pytest
from fastapi import FastAPI, HTTPException, Request
from httpx import ASGITransport, AsyncClient
from starlette.responses import Response

from app.core.config import get_settings
from app.core.middleware import (
    BodySizeLimitMiddleware,
    RateLimitMiddleware,
    RequestIdMiddleware,
    SecurityHeadersMiddleware,
)

MAX_BODY = 100


def _build_app() -> FastAPI:
    app = FastAPI()

    @app.get("/ok")
    async def ok(request: Request):
        # Proves request.state.request_id survived the move to scope["state"].
        return {"request_id": request.state.request_id}

    @app.post("/echo")
    async def echo():
        return {"ok": True}

    @app.get("/boom")
    async def boom():
        raise HTTPException(status_code=418, detail="teapot")

    @app.get("/framed")
    async def framed():
        # A handler that sets a header the middleware also sets: setdefault
        # semantics mean the handler wins and there is no duplicate.
        return Response("framed", headers={"X-Frame-Options": "SAMEORIGIN"})

    # add_middleware PREPENDS, so this reproduces main.py's relative order for
    # these three: SecurityHeaders outermost, then BodySize, then RequestId.
    app.add_middleware(RequestIdMiddleware)
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=MAX_BODY)
    app.add_middleware(SecurityHeadersMiddleware)
    return app


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=_build_app()),
                           base_url="http://test") as c:
        yield c


# ── (a) request id ────────────────────────────────────────────────────────────

async def test_request_id_echoed_and_visible_to_the_route(client):
    resp = await client.get("/ok", headers={"X-Request-ID": "caller-supplied-1"})
    assert resp.status_code == 200
    assert resp.headers["X-Request-ID"] == "caller-supplied-1"
    assert resp.headers.get_list("X-Request-ID") == ["caller-supplied-1"]  # not duplicated
    assert resp.json()["request_id"] == "caller-supplied-1"


async def test_request_id_generated_when_absent(client):
    resp = await client.get("/ok")
    generated = resp.headers["X-Request-ID"]
    assert re.fullmatch(r"req-[0-9a-f]{12}", generated), generated
    assert resp.json()["request_id"] == generated


async def test_request_id_present_on_error_responses(client):
    resp = await client.get("/boom", headers={"X-Request-ID": "err-1"})
    assert resp.status_code == 418
    assert resp.headers["X-Request-ID"] == "err-1"


# ── (b) body size limit ───────────────────────────────────────────────────────

async def test_oversized_body_rejected_with_the_exact_413_payload(client):
    resp = await client.post("/echo", content=b"x" * (MAX_BODY + 1))
    assert resp.status_code == 413
    # Byte-exact: the JSONResponse separators and media type must not drift.
    assert resp.text == '{"detail":"Request body too large (max 100 bytes)."}'
    assert resp.headers["content-type"] == "application/json"


async def test_body_within_limit_passes_through(client):
    resp = await client.post("/echo", content=b"x" * MAX_BODY)
    assert resp.status_code == 200 and resp.json() == {"ok": True}


async def test_malformed_content_length_passes_through():
    reached = []

    async def inner(scope, receive, send):
        reached.append(scope["path"])
        await Response("ok")(scope, receive, send)

    mw = BodySizeLimitMiddleware(inner, max_bytes=MAX_BODY)
    status = await _drive(mw, [(b"content-length", b"not-a-number")])
    assert reached == ["/x"] and status == 200


async def test_non_http_scopes_pass_straight_through():
    seen = []

    async def inner(scope, receive, send):
        seen.append(scope["type"])

    async def receive():  # pragma: no cover - never called
        return {"type": "websocket.connect"}

    async def send(message):  # pragma: no cover - never called
        raise AssertionError("nothing should be sent")

    for mw in (RequestIdMiddleware(inner),
               BodySizeLimitMiddleware(inner, max_bytes=1),
               SecurityHeadersMiddleware(inner)):
        await mw({"type": "websocket", "path": "/ws", "headers": []}, receive, send)
    assert seen == ["websocket"] * 3


async def _drive(mw, headers, path="/x") -> int:
    """Run a pure-ASGI middleware over a synthetic scope, return the status."""
    start = {}

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        if message["type"] == "http.response.start":
            start.update(message)

    await mw({"type": "http", "method": "POST", "path": path, "headers": headers,
              "query_string": b"", "client": ("1.2.3.4", 5)}, receive, send)
    return start["status"]


# ── (c) security headers ──────────────────────────────────────────────────────

async def test_security_headers_present_with_correct_values(client):
    resp = await client.get("/ok")
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    assert resp.headers["X-Frame-Options"] == "DENY"
    assert resp.headers["Referrer-Policy"] == "no-referrer"
    settings = get_settings()
    if settings.DEV_MODE:
        assert resp.headers["Content-Security-Policy"] == SecurityHeadersMiddleware.DEFAULT_CSP
        assert "Strict-Transport-Security" not in resp.headers  # localhost stays HTTP
    else:
        # Outside DEV_MODE the wildcard connect-src is tightened, HSTS is sent.
        assert "wss:" not in resp.headers["Content-Security-Policy"]
        assert resp.headers["Strict-Transport-Security"].startswith("max-age=")


async def test_security_headers_never_override_the_handler(client):
    resp = await client.get("/framed")
    assert resp.headers.get_list("X-Frame-Options") == ["SAMEORIGIN"]
    assert resp.headers["X-Content-Type-Options"] == "nosniff"  # the others still land


async def test_security_headers_on_error_responses(client):
    resp = await client.get("/boom")
    assert resp.status_code == 418
    assert resp.headers["X-Frame-Options"] == "DENY"
    assert "Content-Security-Policy" in resp.headers


# ── (d) rate-limit window eviction (S5.6.9) ───────────────────────────────────

def test_idle_caller_windows_are_evicted():
    mw = RateLimitMiddleware(app=None, requests_per_minute=1000)
    t0 = 1_000_000.0

    for i in range(RateLimitMiddleware.SWEEP_EVERY):
        mw._memory_exceeded(f"scraper-ip-{i}", t0)
    # A sweep ran on the last of those calls, but every window was fresh.
    assert len(mw._windows) == RateLimitMiddleware.SWEEP_EVERY

    # Two minutes later a single live caller drives the next sweep; the 256
    # one-shot callers are now stale and must be gone.
    for i in range(RateLimitMiddleware.SWEEP_EVERY):
        mw._memory_exceeded("live-tenant", t0 + 120 + i * 0.001)
    assert list(mw._windows) == ["live-tenant"]


def test_active_caller_count_is_hard_capped():
    mw = RateLimitMiddleware(app=None, requests_per_minute=1000)
    now = 1_000_000.0
    # All fresh, so the sweep evicts nothing and the cap is what has to hold.
    # The high-water mark is cap + SWEEP_EVERY: the check runs on sweeps only.
    for i in range(RateLimitMiddleware.MAX_TRACKED_CALLERS + RateLimitMiddleware.SWEEP_EVERY):
        mw._memory_exceeded(f"ip-{i}", now)
    assert len(mw._windows) < RateLimitMiddleware.MAX_TRACKED_CALLERS


def test_sweep_keeps_the_caller_that_triggered_it():
    """The sweep runs after the caller's own timestamp is appended, so a caller
    can never evict itself and lose its own in-flight window."""
    mw = RateLimitMiddleware(app=None, requests_per_minute=1000)
    now = 1_000_000.0
    for _ in range(RateLimitMiddleware.SWEEP_EVERY - 1):
        mw._memory_exceeded("noisy", now)
    mw._memory_exceeded("fresh-arrival", now)  # the 256th call: triggers the sweep
    assert set(mw._windows) == {"noisy", "fresh-arrival"}
    assert mw._windows["fresh-arrival"] == [now]
