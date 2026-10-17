"""P1 (launch audit 2026-10-17): a session token is a snapshot of the account at
sign-in. A deactivated or re-roled user's token kept full access for up to
24 h because the middleware trusted the token's role and never re-read the
account. These run the real check against the app's own engine."""
import pytest

import app.core.tenant as T
from app.core.database import MaintenanceSessionLocal
from app.models.auth import User, UserRole
from app.services.auth import AuthService, _create_token

pytestmark = pytest.mark.real_session_check

TENANT = "tenant_fresh"


async def _user(uid: str, role=UserRole.ADMIN, active=True, department=None):
    async with MaintenanceSessionLocal() as db:
        db.add(User(id=uid, email=f"{uid}@example.com", display_name=uid, hashed_password="x",
                    role=role, tenant_id=TENANT, is_active=active, department=department))
        await db.commit()


def _claims(uid: str, role="ADMIN", department=None) -> dict:
    return {"user_id": uid, "tenant_id": TENANT, "role": role, "department": department}


async def test_current_account_passes_and_unknown_is_refused():
    await _user("fresh-ok")
    T.forget_session_user("fresh-ok")
    assert await T.session_refusal(_claims("fresh-ok")) is None
    assert "no longer exists" in await T.session_refusal(_claims("never-existed"))


async def test_deactivation_ends_the_session_immediately():
    await _user("fresh-deact", role=UserRole.ANALYST)
    await _user("fresh-admin")          # so the deactivated one is not the last admin
    assert await T.session_refusal(_claims("fresh-deact", "ANALYST")) is None   # cached now
    async with MaintenanceSessionLocal() as db:
        out = await AuthService.deactivate_user(db, "fresh-deact", TENANT)
    assert out["is_active"] is False
    assert "deactivated" in await T.session_refusal(_claims("fresh-deact", "ANALYST"))
    # found by the live walk: reactivation must take effect at once too
    async with MaintenanceSessionLocal() as db:
        await AuthService.reactivate_user(db, "fresh-deact", TENANT)
    assert await T.session_refusal(_claims("fresh-deact", "ANALYST")) is None


async def test_a_role_change_ends_the_session():
    await _user("fresh-demote")
    assert await T.session_refusal(_claims("fresh-demote")) is None
    async with MaintenanceSessionLocal() as db:
        await AuthService.update_user_role(db, "fresh-demote", UserRole.VIEWER, TENANT)
    assert "access has changed" in await T.session_refusal(_claims("fresh-demote"))
    # a token minted after the change, with the new role, is fine
    assert await T.session_refusal(_claims("fresh-demote", "VIEWER")) is None


async def test_a_token_for_another_tenant_or_department_is_refused():
    await _user("fresh-dept", department="hr")
    T.forget_session_user("fresh-dept")
    assert await T.session_refusal(_claims("fresh-dept", department="hr")) is None
    assert await T.session_refusal(_claims("fresh-dept")) is not None
    assert await T.session_refusal({**_claims("fresh-dept", department="hr"),
                                    "tenant_id": "tenant_other"}) is not None


async def test_middleware_answers_401_for_a_deactivated_users_token(async_client, monkeypatch):
    from app.core.config import get_settings
    settings = get_settings()
    monkeypatch.setattr(settings, "DEV_MODE", False)
    await _user("fresh-mw", role=UserRole.ANALYST, active=False)
    T.forget_session_user("fresh-mw")
    token = _create_token("fresh-mw", "fresh-mw@example.com", "ANALYST", TENANT)
    r = await async_client.get("/api/v1/skills", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401
    assert "deactivated" in r.json()["detail"]
