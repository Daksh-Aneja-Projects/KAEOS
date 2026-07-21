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

        # Precondition: confirm the poisoning actually works on the pinned
        # Starlette (proves this test exercises the bypass). If a future
        # Starlette bump patches GHSA-86qp, this will flip to the real path —
        # revisit the pin/ignore in that case.
        assert request.url.path == "/health"

        called = False

        async def call_next(req):
            nonlocal called
            called = True
            return Response("ok")

        response = await mw.dispatch(request, call_next)

        # The gate must treat this as the PROTECTED route: missing bearer -> 401,
        # and the downstream handler must never run.
        assert response.status_code == 401
        assert called is False
    finally:
        settings.DEV_MODE = prev
