"""Super-admin operator console (/ops) + public /status.

The console reads cross-tenant through the OWNER (maintenance) session, so these
tests seed and read on that same engine (the app engine; MaintenanceSessionLocal
falls back to it in the SQLite test stack) — the pattern established in
test_job_queue.py. The routers are mounted here the way main.py will mount them
(that wiring is RETURNED for a human, not applied to the central file by tests).
"""
import pytest
from httpx import AsyncClient

from app.core.config import get_settings
from app.core.database import engine as app_engine, MaintenanceSessionLocal
from app.main import app
from app.models.auth import Tenant
from app.models.agent_factory import DeployedAgent
from app.models.domain import SkillExecution
from app.api.routes import ops

# Mount exactly as the RETURNED main_py_wiring will.
app.include_router(ops.router, prefix="/api/v1")
app.include_router(ops.status_router)

_SECRET = "test-admin-secret-value"
_OPS_ROUTES = ("/api/v1/ops/tenants", "/api/v1/ops/tenants/tenant_alpha", "/api/v1/ops/overview")


@pytest.fixture(autouse=True)
async def _ops_tables_and_settings():
    s = get_settings()
    prev_dev, prev_secret = s.DEV_MODE, s.ADMIN_SECRET
    s.DEV_MODE = True            # bypass tenant middleware; the /ops gate is separate
    s.ADMIN_SECRET = _SECRET     # so a wrong/absent secret is 403, not 503
    async with app_engine.begin() as conn:
        for tbl in (Tenant.__table__, DeployedAgent.__table__, SkillExecution.__table__):
            await conn.run_sync(tbl.create, checkfirst=True)
        from sqlalchemy import text
        for t in ("skill_executions", "deployed_agents", "tenants"):
            await conn.execute(text(f"DELETE FROM {t}"))
    yield
    s.DEV_MODE, s.ADMIN_SECRET = prev_dev, prev_secret


async def _seed():
    async with MaintenanceSessionLocal() as db:
        db.add(Tenant(tenant_id="tenant_alpha", name="Alpha Corp", plan="business", is_active=True))
        db.add(Tenant(tenant_id="tenant_beta", name="Beta LLC", plan="free", is_active=False))
        db.add(DeployedAgent(tenant_id="tenant_alpha", blueprint_id="bp1", agent_name="a1"))
        db.add(SkillExecution(tenant_id="tenant_alpha", skill_id_name="s1",
                              status="SUCCESS_CLEAN", hitl_required=False, outcome_type="SUCCESS_CLEAN"))
        db.add(SkillExecution(tenant_id="tenant_beta", skill_id_name="s2",
                              status="HUMAN_OVERRIDDEN", hitl_required=True, outcome_type="HUMAN_OVERRIDDEN"))
        await db.commit()


@pytest.mark.parametrize("route", _OPS_ROUTES)
async def test_ops_requires_superadmin_missing_secret_403(async_client: AsyncClient, route):
    """No X-Admin-Secret -> 403 on every /ops route (fails closed)."""
    r = await async_client.get(route)
    assert r.status_code == 403, r.text


@pytest.mark.parametrize("route", _OPS_ROUTES)
async def test_ops_requires_superadmin_wrong_secret_403(async_client: AsyncClient, route):
    """A non-super-admin (wrong secret) is denied on every /ops route."""
    r = await async_client.get(route, headers={"X-Admin-Secret": "not-the-secret"})
    assert r.status_code == 403, r.text


async def test_ops_tenants_lists_cross_tenant(async_client: AsyncClient):
    """With the super-admin secret, the owner-session read returns >1 tenant."""
    await _seed()
    r = await async_client.get("/api/v1/ops/tenants", headers={"X-Admin-Secret": _SECRET})
    assert r.status_code == 200, r.text
    body = r.json()
    ids = {t["id"] for t in body["tenants"]}
    assert {"tenant_alpha", "tenant_beta"}.issubset(ids)
    assert body["count"] >= 2
    alpha = next(t for t in body["tenants"] if t["id"] == "tenant_alpha")
    assert alpha["agent_count"] == 1 and alpha["execution_count"] == 1


async def test_ops_tenant_detail(async_client: AsyncClient):
    await _seed()
    r = await async_client.get("/api/v1/ops/tenants/tenant_alpha", headers={"X-Admin-Secret": _SECRET})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["plan"] == "business"
    assert "webhooks" in body["entitlements"]         # business plan includes webhooks
    assert body["usage"]["plan"] == "business"
    assert body["health"]["agent_count"] == 1


async def test_ops_tenant_detail_unknown_404(async_client: AsyncClient):
    r = await async_client.get("/api/v1/ops/tenants/nope", headers={"X-Admin-Secret": _SECRET})
    assert r.status_code == 404, r.text


async def test_ops_overview_totals_and_honesty(async_client: AsyncClient):
    await _seed()
    r = await async_client.get("/api/v1/ops/overview", headers={"X-Admin-Secret": _SECRET})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["tenant_count"] >= 2
    assert body["active_tenants"] >= 1
    assert body["total_executions"] >= 2
    assert body["plan_distribution"].get("business", 0) >= 1
    # 2 execs, 1 clean-autonomous -> 0.5 blended (a real number, not fabricated)
    assert body["blended_safe_autonomy_rate"] == 0.5


async def test_status_public_no_auth_and_no_tenant_leak(async_client: AsyncClient):
    """/status needs no auth and must never leak tenant-identifying data."""
    await _seed()
    r = await async_client.get("/status")   # no Authorization, no admin secret
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "ok"
    assert set(body["dependencies"]) == {"db", "redis", "llm"}
    assert body["dependencies"]["db"] is True
    assert "version" in body and "uptime_seconds" in body
    # No per-tenant identifiers anywhere in the public payload.
    raw = r.text
    for leak in ("tenant_alpha", "tenant_beta", "Alpha Corp", "Beta LLC"):
        assert leak not in raw


async def test_status_does_not_expose_business_metric(async_client: AsyncClient):
    """The public /status must NOT publish the platform safe-autonomy rate: it is
    a business metric and its cross-tenant aggregate is an unindexed full scan (a
    DoS amplifier on an auth-free endpoint). It lives on gated /ops/overview."""
    r = await async_client.get("/status")
    assert r.status_code == 200, r.text
    assert "platform_safe_autonomy_rate" not in r.json()
