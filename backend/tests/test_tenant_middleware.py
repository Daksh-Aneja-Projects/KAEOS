import pytest
from httpx import AsyncClient
from starlette.requests import Request
from starlette.responses import Response

from app.core.config import get_settings
from app.core.tenant import TenantMiddleware

@pytest.mark.asyncio
async def test_tenant_middleware_dev_mode(async_client: AsyncClient):
    """
    Test that DEV_MODE allows bypass with any token and assigns tenant_acme.
    """
    settings = get_settings()
    settings.DEV_MODE = True
    
    response = await async_client.get("/api/v1/workforce/departments", headers={"Authorization": "Bearer fake_token"})
    assert response.status_code == 200
    
@pytest.mark.asyncio
async def test_tenant_middleware_prod_mode(async_client: AsyncClient):
    """
    Test that DEV_MODE=False requires a valid token.
    """
    settings = get_settings()
    settings.DEV_MODE = False
    
    response = await async_client.get("/api/v1/workforce/departments", headers={"Authorization": "Bearer fake_token"})
    assert response.status_code == 401
    
    # Restore dev mode for other tests
    settings.DEV_MODE = True


@pytest.mark.asyncio
async def test_poisoned_host_header_cannot_bypass_auth_gate():
    """GHSA-86qp regression: a malformed Host header must NOT let an
    unauthenticated caller reach a protected route.

    Starlette (<1.0.1, and no FastAPI supports 1.x) rebuilds ``request.url``
    from the attacker-controlled Host header, so ``Host: evil/health?x=`` makes
    ``request.url.path`` read ``/health`` while the router still dispatches the
    real protected path from ``scope["path"]``. The tenant gate must key off the
    raw scope path, not ``request.url.path``.
    """
    settings = get_settings()
    prev = settings.DEV_MODE
    settings.DEV_MODE = False  # enforce real auth
    try:
        mw = TenantMiddleware(app=None)
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/workforce/departments",  # real routed path — PROTECTED
            "raw_path": b"/api/v1/workforce/departments",
            # Host with '/' and '?' poisons the url reconstruction to "/health"
            "headers": [(b"host", b"evil.test/health?x=")],
            "query_string": b"",
            "scheme": "http",
            "server": ("testserver", 80),
        }

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        request = Request(scope, receive)

        # Which regime are we on? Starlette <1.0.1 rebuilds request.url from the
        # Host header, so the poisoning lands and request.url.path reads
        # "/health" (GHSA-86qp). Starlette >=1.0.1 patches it and the real path
        # comes back. BOTH are acceptable here — what must hold either way is the
        # security property asserted below: the gate keys off scope["path"], so a
        # poisoned Host can never reach a protected route unauthenticated.
        # Asserting the vulnerable value as a precondition would make this test
        # fail on a PATCHED Starlette, i.e. break on a security improvement.
        upstream_vulnerable = request.url.path == "/health"
        assert request.url.path in ("/health", "/api/v1/workforce/departments"), (
            f"unexpected url.path {request.url.path!r} — Starlette changed URL "
            "reconstruction again; re-check the gate's scope['path'] usage"
        )
        assert request.scope["path"] == "/api/v1/workforce/departments", (
            "scope['path'] is the router's matched path and must never be "
            "influenced by the Host header"
        )

        called = False

        async def call_next(req):
            nonlocal called
            called = True
            return Response("ok")

        response = await mw.dispatch(request, call_next)

        # The gate must treat this as the PROTECTED route: missing bearer -> 401,
        # and the downstream handler must never run. This is the invariant that
        # matters, and it holds on a vulnerable AND a patched Starlette — the
        # scope["path"] mitigation stays as defense in depth either way.
        assert response.status_code == 401, (
            "poisoned Host reached a protected route "
            f"(upstream_vulnerable={upstream_vulnerable}) — the gate must read "
            "request.scope['path'], never request.url.path"
        )
        assert called is False
    finally:
        settings.DEV_MODE = prev
