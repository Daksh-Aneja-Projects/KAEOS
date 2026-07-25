"""Department-scoped RBAC - an HR-scoped user is confined to the HR surface.

The contract under test:
  * scoped user (department='hr'): own domain 200, other domains 403,
    cross-domain aggregates (org pulse) still readable - that insight is the IP
  * org-wide user (no department claim): everything as before
  * missions: scoped users see only missions touching their department and
    cannot act on cross-department missions
  * user management: admins can set/clear a user's department scope
"""
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.core.database import init_db
from app.services.auth import _create_token

TENANT = "tenant_acme"


def _headers(role: str = "ANALYST", department: str | None = None) -> dict:
    token = _create_token(f"u-{role}-{department or 'org'}", f"{role}@kaeos.ai",
                          role, TENANT, department=department)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(autouse=True)
def _enforce_auth():
    """DEV_MODE resolves every request to an org-wide admin dev tenant, which
    would bypass department scoping - enforcement is a DEV_MODE=false concern
    (same approach as test_rbac_coverage)."""
    from app.core.config import get_settings
    settings = get_settings()
    prev = settings.DEV_MODE
    settings.DEV_MODE = False
    yield
    settings.DEV_MODE = prev


@pytest_asyncio.fixture()
async def client():
    await init_db()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_scoped_user_allowed_on_own_domain(client):
    resp = await client.get("/api/v1/hr/employees",
                            headers=_headers(department="hr"))
    assert resp.status_code == 200, resp.text


@pytest.mark.asyncio
async def test_scoped_user_denied_on_other_domain(client):
    resp = await client.get("/api/v1/finance/dashboard",
                            headers=_headers(department="hr"))
    assert resp.status_code == 403
    assert "hr" in resp.json()["detail"]

    # and the other direction: a finance-scoped user cannot read HR employees
    resp = await client.get("/api/v1/hr/employees",
                            headers=_headers(department="finance"))
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_org_wide_user_unaffected(client):
    for path in ("/api/v1/hr/employees", "/api/v1/finance/dashboard"):
        resp = await client.get(path, headers=_headers())
        assert resp.status_code == 200, f"{path}: {resp.status_code} {resp.text[:200]}"


@pytest.mark.asyncio
async def test_cross_domain_aggregates_stay_readable(client):
    """Org pulse and the departments LIST are the IP - readable for scoped users."""
    resp = await client.get("/api/v1/org/pulse", headers=_headers(department="hr"))
    assert resp.status_code == 200, resp.text
    resp = await client.get("/api/v1/workforce/departments",
                            headers=_headers(department="hr"))
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_department_detail_scoped(client):
    """Own department detail opens; another department's detail is 403."""
    own = await client.get("/api/v1/workforce/departments/hr",
                           headers=_headers(department="hr"))
    assert own.status_code in (200, 404)   # 404 only if the dept is not seeded
    other = await client.get("/api/v1/workforce/departments/finance",
                             headers=_headers(department="hr"))
    if other.status_code != 404:           # dept exists -> must be denied
        assert other.status_code == 403


@pytest.mark.asyncio
async def test_missions_list_filtered_by_scope(client, db):
    """Create a finance-only mission as org-wide; the HR-scoped list omits it.

    Rows are written through the conftest `db` fixture (the same test engine
    the routes read via the get_db override) - the dual-engine trap.
    """
    from app.models.missions import Mission
    db.add(Mission(id="m-fin-rbac", tenant_id=TENANT,
                   goal="close the books", status="RUNNING",
                   departments=["finance"]))
    db.add(Mission(id="m-hr-rbac", tenant_id=TENANT,
                   goal="onboard a hire", status="RUNNING",
                   departments=["hr", "finance"]))
    await db.commit()

    resp = await client.get("/api/v1/missions", headers=_headers(department="hr"))
    assert resp.status_code == 200
    ids = {m["id"] for m in resp.json()["missions"]}
    assert "m-hr-rbac" in ids            # touches HR -> visible
    assert "m-fin-rbac" not in ids       # finance-only -> hidden

    # org-wide sees both
    resp = await client.get("/api/v1/missions", headers=_headers())
    ids = {m["id"] for m in resp.json()["missions"]}
    assert {"m-hr-rbac", "m-fin-rbac"} <= ids


@pytest.mark.asyncio
async def test_scoped_user_cannot_act_on_cross_department_mission(client, db):
    """Advancing a mission that spans finance is denied for an HR-scoped user."""
    from app.models.missions import Mission
    db.add(Mission(id="m-hr-rbac-2", tenant_id=TENANT,
                   goal="onboard a hire", status="RUNNING",
                   departments=["hr", "finance"]))
    db.add(Mission(id="m-fin-rbac-2", tenant_id=TENANT,
                   goal="close the books", status="RUNNING",
                   departments=["finance"]))
    await db.commit()

    resp = await client.post("/api/v1/missions/m-hr-rbac-2/advance",
                             headers=_headers(department="hr"))
    assert resp.status_code == 403       # spans finance too -> whole-mission act denied
    resp = await client.post("/api/v1/missions/m-fin-rbac-2/advance",
                             headers=_headers(department="hr"))
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_admin_sets_and_clears_department_scope(client, db):
    # The /auth/users routes verify the CALLER exists and is active, so seed a
    # real admin row whose id matches the minted token.
    from app.models.auth import User, UserRole
    admin_row = User(id="u-rbac-admin", email="rbac.admin@kaeos.ai",
                     display_name="RBAC Admin", hashed_password="x",
                     role=UserRole.ADMIN, tenant_id=TENANT, is_active=True)
    db.add(admin_row)
    await db.commit()
    token = _create_token("u-rbac-admin", "rbac.admin@kaeos.ai", "ADMIN", TENANT)
    admin = {"Authorization": f"Bearer {token}"}

    # create a user to scope
    resp = await client.post("/api/v1/auth/users", headers=admin, json={
        "email": "hr.person@kaeos.ai", "display_name": "HR Person",
        "password": "a-strong-password-123", "role": "ANALYST"})
    assert resp.status_code == 200, resp.text
    uid = resp.json()["id"]

    resp = await client.put(f"/api/v1/auth/users/{uid}/department",
                            headers=admin, json={"department": "hr"})
    assert resp.status_code == 200 and resp.json()["department"] == "hr"

    # invalid department rejected
    resp = await client.put(f"/api/v1/auth/users/{uid}/department",
                            headers=admin, json={"department": "wizardry"})
    assert resp.status_code == 400

    # listed with the scope
    resp = await client.get("/api/v1/auth/users", headers=admin)
    row = next(u for u in resp.json() if u["id"] == uid)
    assert row["department"] == "hr"

    # clear back to org-wide
    resp = await client.put(f"/api/v1/auth/users/{uid}/department",
                            headers=admin, json={"department": None})
    assert resp.status_code == 200 and resp.json()["department"] is None
