"""White-label branding: defaults, admin-only writes, validation, tenant scoping.

Self-wires the router and model — the real main.py / database.py registration is
returned as data for a human to integrate (central files this workstream must not
edit), so the test mounts them itself to prove the behavior end to end. Importing
the model at module load registers brand_tenant_branding in Base.metadata, which
conftest's create_all then builds.
"""
import pytest

from app.main import app
from app.core.config import get_settings
from app.services.auth import _create_token
from app.api.routes import branding as branding_route
from app.models.branding import TenantBranding  # noqa: F401 — registers the table

# Mount once (idempotent across the reused app instance).
if not any(getattr(r, "path", "") == "/branding" for r in app.routes):
    app.include_router(branding_route.router)


@pytest.mark.asyncio
async def test_default_brand_when_unset(async_client):
    r = await async_client.get("/branding", headers={"X-Tenant-ID": "t_default_probe"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["is_default"] is True
    assert body["product_name"] == "KAEOS"
    assert body["primary_color"].startswith("#")
    assert body["logo_url"] is None


@pytest.mark.asyncio
async def test_put_by_non_admin_is_403(async_client):
    settings = get_settings()
    prev = settings.DEV_MODE
    settings.DEV_MODE = False
    try:
        token = _create_token("u-view", "v@kaeos.ai", "VIEWER", "tenant_acme")
        r = await async_client.put(
            "/branding",
            headers={"Authorization": f"Bearer {token}"},
            json={"primary_color": "#123456", "accent_color": "#abcdef"},
        )
        assert r.status_code == 403, r.text
    finally:
        settings.DEV_MODE = prev


@pytest.mark.asyncio
@pytest.mark.parametrize("payload,field", [
    ({"primary_color": "red", "accent_color": "#abcdef"}, "primary_color"),
    ({"primary_color": "#12345", "accent_color": "#abcdef"}, "primary_color"),   # 5 hex digits
    ({"primary_color": "#123456", "accent_color": "nope"}, "accent_color"),
    ({"primary_color": "#123456", "accent_color": "#abcdef",
      "logo_url": "javascript:alert(1)"}, "logo_url"),
    ({"primary_color": "#123456", "accent_color": "#abcdef",
      "logo_url": "data:text/html,<script>x</script>"}, "logo_url"),
    ({"primary_color": "#123456", "accent_color": "#abcdef",
      "logo_url": "/relative/logo.png"}, "logo_url"),
])
async def test_invalid_values_rejected(async_client, payload, field):
    # DEV_MODE default → admin dev tenant, so the gate admits us and we reach
    # validation (a 400, not a 403).
    r = await async_client.put(
        "/branding", headers={"X-Tenant-ID": "t_valid"}, json=payload,
    )
    assert r.status_code == 400, r.text
    assert field in r.json()["detail"]


@pytest.mark.asyncio
async def test_values_round_trip_and_are_tenant_scoped(async_client):
    put = await async_client.put(
        "/branding",
        headers={"X-Tenant-ID": "t_one"},
        json={
            "product_name": "AcmeOps",
            "primary_color": "#AA11BB",
            "accent_color": "#00FFcc",
            "logo_url": "https://cdn.acme.example/logo.svg",
            "login_subtitle": "Governed AI for Acme",
        },
    )
    assert put.status_code == 200, put.text
    saved = put.json()
    assert saved["product_name"] == "AcmeOps"
    assert saved["primary_color"] == "#aa11bb"   # normalized lowercase
    assert saved["logo_url"] == "https://cdn.acme.example/logo.svg"
    assert saved["is_default"] is False

    # Same tenant reads it back.
    got = await async_client.get("/branding", headers={"X-Tenant-ID": "t_one"})
    assert got.json()["product_name"] == "AcmeOps"
    assert got.json()["is_default"] is False

    # A DIFFERENT tenant still gets defaults — the brand did not leak.
    other = await async_client.get("/branding", headers={"X-Tenant-ID": "t_two"})
    assert other.json()["is_default"] is True
    assert other.json()["product_name"] == "KAEOS"
