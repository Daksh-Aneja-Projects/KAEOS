"""Billing surfaces: plan catalog on /entitlements, Stripe checkout/portal
sessions (404 on self-host Noop, URL pass-through on a real provider), and the
SkillValueBaseline CRUD that feeds the honest ROI figure.
"""
import pytest

from app.services import stripe_bridge
from app.services.auth import _create_token

TENANT = "tenant_acme"


@pytest.fixture(autouse=True)
def _reset_provider():
    """Each test picks its provider fresh; never leak a stub across tests."""
    stripe_bridge.reset_billing_provider()
    yield
    stripe_bridge.reset_billing_provider()


# ---------------------------------------------------------------- catalog

@pytest.mark.asyncio
async def test_entitlements_catalog_additive_keys(async_client):
    resp = await async_client.get("/api/v1/billing/entitlements")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # Existing keys unchanged - OperatorConsole/ops consume them.
    for key in ("tenant_id", "plan", "managed_cloud", "features", "usage"):
        assert key in body, f"existing key '{key}' disappeared"
    assert isinstance(body["features"], dict)
    assert "included_allowance" in body["usage"]
    # Additive plan catalog serialized from PLAN_FEATURES/PLAN_ALLOWANCE.
    plans = body["plans"]
    assert set(plans) == {"free", "oss", "team", "business", "enterprise"}
    assert plans["team"]["allowance"] == 5000
    assert "webhooks" in plans["team"]["features"]
    assert plans["enterprise"]["features"] == sorted(
        ["webhooks", "sso", "scim", "advanced_connectors"])
    # No BillingAccount row seeded -> seats is null, not fabricated.
    assert body["seats"] is None


@pytest.mark.asyncio
async def test_entitlements_seats_from_billing_account(async_client, db):
    from app.models.billing import BillingAccount
    db.add(BillingAccount(tenant_id=TENANT, seats=7))
    await db.commit()
    resp = await async_client.get("/api/v1/billing/entitlements")
    assert resp.status_code == 200
    assert resp.json()["seats"] == 7


# ------------------------------------------------- checkout / portal sessions

@pytest.mark.asyncio
async def test_checkout_and_portal_404_on_noop_provider(async_client):
    resp = await async_client.post(
        "/api/v1/billing/checkout-session", json={"plan": "team"})
    assert resp.status_code == 404
    assert "not enabled" in resp.json()["detail"]
    resp = await async_client.post("/api/v1/billing/portal-session")
    assert resp.status_code == 404


class _StubProvider(stripe_bridge.BillingProvider):
    enabled = True

    def __init__(self):
        self.calls = []

    async def create_checkout_session(self, db, tenant_id, plan, success_url, cancel_url):
        self.calls.append(("checkout", tenant_id, plan, success_url, cancel_url))
        return "https://checkout.stripe.test/cs_123"

    async def create_portal_session(self, db, tenant_id, return_url):
        self.calls.append(("portal", tenant_id, return_url))
        return "https://portal.stripe.test/bps_123"


@pytest.mark.asyncio
async def test_checkout_and_portal_happy_path_with_stubbed_provider(async_client):
    stub = _StubProvider()
    stripe_bridge._provider = stub

    resp = await async_client.post(
        "/api/v1/billing/checkout-session", json={"plan": "team"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["url"] == "https://checkout.stripe.test/cs_123"
    kind, tenant_id, plan, success_url, cancel_url = stub.calls[0]
    assert (kind, tenant_id, plan) == ("checkout", TENANT, "team")
    # Redirect lands back on the Billing tab, not the default settings tab.
    assert success_url.endswith("/platform/settings?tab=billing")
    assert cancel_url.endswith("/platform/settings?tab=billing")

    resp = await async_client.post("/api/v1/billing/portal-session")
    assert resp.status_code == 200, resp.text
    assert resp.json()["url"] == "https://portal.stripe.test/bps_123"
    assert stub.calls[1][0] == "portal"


@pytest.mark.asyncio
async def test_checkout_rejects_unpurchasable_plans(async_client):
    stripe_bridge._provider = _StubProvider()
    for plan in ("free", "oss", "mystery"):
        resp = await async_client.post(
            "/api/v1/billing/checkout-session", json={"plan": plan})
        assert resp.status_code == 400, f"{plan}: {resp.status_code}"


# ---------------------------------------------------------------- baselines

@pytest.mark.asyncio
async def test_baselines_upsert_and_list(async_client):
    up = {"skill_name": "invoice_triage", "baseline_minutes": 30, "hourly_rate": 85}
    resp = await async_client.put("/api/v1/billing/baselines", json=up)
    assert resp.status_code == 200, resp.text
    assert resp.json() == {
        "skill_name": "invoice_triage", "baseline_minutes": 30, "hourly_rate": 85.0}

    # Same skill again: upsert on the unique constraint, not a second row.
    up["baseline_minutes"] = 45
    resp = await async_client.put("/api/v1/billing/baselines", json=up)
    assert resp.status_code == 200, resp.text

    resp = await async_client.get("/api/v1/billing/baselines")
    assert resp.status_code == 200
    rows = [r for r in resp.json()["baselines"] if r["skill_name"] == "invoice_triage"]
    assert len(rows) == 1
    assert rows[0]["baseline_minutes"] == 45
    assert rows[0]["hourly_rate"] == 85.0


@pytest.mark.asyncio
async def test_baselines_validation(async_client):
    resp = await async_client.put(
        "/api/v1/billing/baselines", json={"skill_name": "  ", "baseline_minutes": 5})
    assert resp.status_code == 400
    resp = await async_client.put(
        "/api/v1/billing/baselines", json={"skill_name": "x", "baseline_minutes": -1})
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_billing_admin_surfaces_403_for_non_admin(async_client):
    """DEV_MODE resolves every request to an admin dev tenant, so enforcement is
    exercised with DEV_MODE=false and a minted VIEWER JWT (test_department_rbac
    idiom)."""
    from app.core.config import get_settings
    settings = get_settings()
    prev = settings.DEV_MODE
    settings.DEV_MODE = False
    try:
        token = _create_token("u-billing-viewer", "viewer@kaeos.ai", "VIEWER", TENANT)
        headers = {"Authorization": f"Bearer {token}"}
        resp = await async_client.put(
            "/api/v1/billing/baselines", headers=headers,
            json={"skill_name": "x", "baseline_minutes": 5})
        assert resp.status_code == 403
        resp = await async_client.get("/api/v1/billing/baselines", headers=headers)
        assert resp.status_code == 403
        resp = await async_client.post(
            "/api/v1/billing/checkout-session", headers=headers, json={"plan": "team"})
        assert resp.status_code == 403
        resp = await async_client.post(
            "/api/v1/billing/portal-session", headers=headers)
        assert resp.status_code == 403
    finally:
        settings.DEV_MODE = prev
