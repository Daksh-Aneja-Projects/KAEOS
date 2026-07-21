"""
RBAC coverage — proves the write endpoints hardened in the "Limitations tail"
work now carry an explicit role gate, and that the gate actually denies an
under-privileged caller.

Why this lives in the unit lane, not tests/e2e/:
  The e2e `client` fixture targets a DEV_MODE=true backend, where TenantMiddleware
  resolves EVERY request to an admin dev tenant regardless of token — so
  require_role can never be exercised there (conftest documents this). Auth
  ENFORCEMENT is a DEV_MODE=false concern, which the in-memory ASGI harness here
  can toggle. We therefore verify three things without a live server:

    1. Introspection — each newly-gated (method, path) has a require_role
       dependency wired into its FastAPI route. This locks the coverage in and
       fails loudly if a future edit drops a gate.
    2. Functional denial — with DEV_MODE off, a VIEWER JWT hitting a gated
       endpoint gets 403 (the gate fires BEFORE any handler logic, so this is
       robust even with an empty in-memory DB).
    3. require_role logic — the dependency itself denies/permits by role level.
"""
import pytest
from fastapi import HTTPException

from app.main import app
from app.core.config import get_settings
from app.core.tenant import require_role
from app.services.auth import _create_token

# ── The endpoints hardened in this pass ──────────────────────────────────────
# (HTTP method, route path as registered — includes the /api/v1 prefix and any
#  {path_param} braces). Kept explicit so the introspection test doubles as the
#  authoritative list of what this change gated.
OPERATOR_GATED = [
    ("POST", "/api/v1/elicitation/answer"),
    ("POST", "/api/v1/elicitation/generate"),
    ("POST", "/api/v1/intelligence/signals"),
    ("POST", "/api/v1/foundry/feedback"),
    ("POST", "/api/v1/pipeline/run"),
    ("POST", "/api/v1/infrastructure/agents/{agent_name}/circuit/reset"),
    ("POST", "/api/v1/infrastructure/schema-mappings/{mapping_id}/confirm"),
]
ADMIN_GATED = [
    ("POST", "/api/v1/polymorphic/synthesize"),
]
ALL_GATED = OPERATOR_GATED + ADMIN_GATED


def _dependant_uses_require_role(dependant) -> bool:
    """Recursively scan a FastAPI Dependant tree for a require_role checker.

    require_role() returns a closure named `require_role.<locals>._checker`, so
    the qualname is a stable, import-free fingerprint.
    """
    call = getattr(dependant, "call", None)
    if call is not None and "require_role" in getattr(call, "__qualname__", ""):
        return True
    return any(_dependant_uses_require_role(sub) for sub in getattr(dependant, "dependencies", []))


def _find_route(method: str, path: str):
    for route in app.routes:
        if getattr(route, "path", None) == path and method in getattr(route, "methods", set()):
            return route
    return None


@pytest.mark.parametrize("method,path", ALL_GATED)
def test_gated_route_declares_require_role(method, path):
    """Each hardened endpoint must carry a require_role dependency (regression lock)."""
    route = _find_route(method, path)
    assert route is not None, f"Route {method} {path} not found — path may have changed"
    assert _dependant_uses_require_role(route.dependant), (
        f"{method} {path} lost its require_role gate"
    )


def test_require_role_denies_and_permits_by_level():
    """The require_role dependency: viewer < operator < admin, denials raise 403."""
    op_checker = require_role("operator")
    admin_checker = require_role("admin")

    viewer = {"tenant_id": "t", "role": "viewer"}
    operator = {"tenant_id": "t", "role": "operator"}
    admin = {"tenant_id": "t", "role": "admin"}

    # operator gate
    with pytest.raises(HTTPException) as ei:
        op_checker(tenant=viewer)
    assert ei.value.status_code == 403
    assert op_checker(tenant=operator) is operator
    assert op_checker(tenant=admin) is admin

    # admin gate
    with pytest.raises(HTTPException) as ei2:
        admin_checker(tenant=operator)
    assert ei2.value.status_code == 403
    assert admin_checker(tenant=admin) is admin


@pytest.mark.asyncio
@pytest.mark.parametrize("method,path", ALL_GATED)
async def test_viewer_denied_on_gated_endpoint(async_client, method, path):
    """With auth enforced (DEV_MODE off), a VIEWER JWT is 403'd on every gate.

    The gate fires before handler logic, so an empty in-memory DB is irrelevant —
    a viewer never reaches the body. We assert 403 specifically (not merely a
    4xx): 401 would mean the token was rejected, 200/404/500 would mean the gate
    was skipped.
    """
    settings = get_settings()
    prev = settings.DEV_MODE
    settings.DEV_MODE = False
    try:
        token = _create_token("u-viewer", "viewer@kaeos.ai", "VIEWER", "tenant_acme")
        # Fill any {param} placeholders with a dummy value; the gate runs first.
        concrete = path.replace("{agent_name}", "x").replace("{mapping_id}", "x")
        r = await async_client.request(
            method, concrete,
            headers={"Authorization": f"Bearer {token}"},
            json={},
        )
        assert r.status_code == 403, (
            f"{method} {concrete}: expected 403 for viewer, got {r.status_code}: {r.text[:200]}"
        )
    finally:
        settings.DEV_MODE = prev


@pytest.mark.asyncio
async def test_operator_passes_operator_gate(async_client):
    """An ANALYST(→operator) JWT clears an operator gate (not 401/403).

    We use /pipeline/run: with an empty DB / no real connector the handler will
    error downstream, but crucially NOT with 401/403 — proving the gate admitted
    the operator rather than blocking them.
    """
    settings = get_settings()
    prev = settings.DEV_MODE
    settings.DEV_MODE = False
    try:
        token = _create_token("u-op", "op@kaeos.ai", "ANALYST", "tenant_acme")
        r = await async_client.post(
            "/api/v1/pipeline/run",
            headers={"Authorization": f"Bearer {token}"},
            json={"connector_slug": "csv", "connector_config": {}},
        )
        assert r.status_code not in (401, 403), (
            f"operator was blocked by the gate: {r.status_code}: {r.text[:200]}"
        )
    finally:
        settings.DEV_MODE = prev
