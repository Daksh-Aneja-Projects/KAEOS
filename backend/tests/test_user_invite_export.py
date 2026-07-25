"""User invite/reactivation (magic-link) + audit CSV export."""
import uuid

import pytest

from app.services.auth import AuthService
from app.models.auth import User, UserRole
from app.api.routes import auth as auth_routes

pytestmark = pytest.mark.asyncio

T = "tenant_inv"


async def test_invite_then_accept_activates_without_admin_password(db):
    res = await AuthService.invite_user(
        db, email="invitee@corp.com", display_name="Invitee",
        role=UserRole.ANALYST, created_by="admin1", tenant_id=T,
    )
    assert "invite_token" in res and res["is_active"] is False

    # Before acceptance the account is inactive and cannot be logged into.
    from sqlalchemy import select
    u = (await db.execute(select(User).where(User.email == "invitee@corp.com"))).scalar_one()
    assert u.is_active is False

    # A weak password is rejected.
    weak = await AuthService.accept_invite(db, res["invite_token"], "short")
    assert weak.get("error") == "weak_password"

    # Accepting with a strong password sets it and activates the account.
    ok = await AuthService.accept_invite(db, res["invite_token"], "a-strong-password-123")
    assert ok["is_active"] is True
    u2 = (await db.execute(select(User).where(User.email == "invitee@corp.com"))).scalar_one()
    assert u2.is_active is True
    from app.services.auth import _verify_password
    assert _verify_password("a-strong-password-123", u2.hashed_password)


async def test_accept_invite_rejects_tampered_token(db):
    res = await AuthService.invite_user(
        db, email="x@corp.com", display_name="X", role=UserRole.VIEWER,
        created_by="a", tenant_id=T,
    )
    bad = await AuthService.accept_invite(db, res["invite_token"] + "x", "a-strong-password-123")
    assert bad.get("error") == "invalid_or_expired_invite"


async def test_reactivate_reverses_deactivation(db):
    u = User(id=str(uuid.uuid4()), email="re@corp.com", display_name="Re",
             hashed_password="x", role=UserRole.VIEWER, tenant_id=T, is_active=True)
    db.add(u)
    await db.commit()

    await AuthService.deactivate_user(db, u.id, tenant_id=T)
    from sqlalchemy import select
    assert (await db.execute(select(User).where(User.id == u.id))).scalar_one().is_active is False

    out = await AuthService.reactivate_user(db, u.id, tenant_id=T)
    assert out["is_active"] is True
    assert (await db.execute(select(User).where(User.id == u.id))).scalar_one().is_active is True


async def test_reactivate_is_tenant_scoped(db):
    u = User(id=str(uuid.uuid4()), email="other@corp.com", display_name="O",
             hashed_password="x", role=UserRole.VIEWER, tenant_id="tenant_other", is_active=False)
    db.add(u)
    await db.commit()
    # A different tenant cannot reactivate it.
    out = await AuthService.reactivate_user(db, u.id, tenant_id=T)
    assert out.get("error") == "user_not_found"


async def test_compliance_csv_export_has_header_and_rows(db):
    from app.models.domain import Rule
    from app.hr.models.compliance import ComplianceViolation
    db.add(Rule(id=str(uuid.uuid4()), tenant_id=T, statement="s", trigger_json={},
                action_json={}, compliance_tags=["GDPR"], is_archived=False))
    db.add(ComplianceViolation(id=str(uuid.uuid4()), tenant_id=T, framework="GDPR",
                               severity="BLOCKER", description="d", resolved=False))
    await db.commit()

    resp = await auth_export_compliance(T, db)
    body = resp.body.decode()
    assert resp.media_type == "text/csv"
    assert "framework,status,coverage_pct,violations,blocker_count,last_audit" in body
    assert "GDPR" in body and "REVIEW" in body


async def auth_export_compliance(tenant_id, db):
    # thin wrapper so the test reads clearly
    from app.api.routes.dashboard import compliance_export
    return await compliance_export(tenant_id=tenant_id, db=db)
