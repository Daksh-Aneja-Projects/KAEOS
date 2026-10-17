"""Login hardening from the launch audit (2026-10-17).

* Lockout was keyed on the e-mail alone, so anyone could lock any account out
  with five bad passwords. It is now keyed on e-mail + address, with a wider
  e-mail-only cap so a botnet still cannot guess forever.
* The failure counter was cleared on a right password BEFORE the second factor
  was checked, so a wrong TOTP code never accumulated: it is cleared only
  after both factors.
* Every anonymous (pre-auth) request shared one rate-limit bucket, so 1,100
  bad logins from one address locked everyone out of signing in.
"""
import uuid

import pytest
from starlette.requests import Request

from app.core.config import get_settings
from app.models.auth import User, UserRole
from app.services import auth as auth_mod
from app.services.auth import AuthService, _hash_password


@pytest.fixture(autouse=True)
def _no_redis(monkeypatch):
    async def none():
        return None
    monkeypatch.setattr(auth_mod, "_redis", none)
    auth_mod._failed_logins.clear()
    yield
    auth_mod._failed_logins.clear()


async def _user(db, email: str, password: str) -> User:
    u = User(id=str(uuid.uuid4()), email=email, display_name=email,
             hashed_password=await _hash_password(password), role=UserRole.ANALYST,
             tenant_id="tenant_login", is_active=True)
    db.add(u)
    await db.commit()
    return u


async def test_bad_passwords_from_one_address_do_not_lock_the_owner_out_elsewhere(db):
    await _user(db, "owner@example.com", "the-right-password-1")
    n = get_settings().LOGIN_MAX_FAILURES
    for _ in range(n):
        assert await AuthService.login(db, "owner@example.com", "wrong", ip_address="203.0.113.9") is None
    # the attacker's address is locked out, even with the right password
    assert await AuthService.login(db, "owner@example.com", "the-right-password-1",
                                   ip_address="203.0.113.9") is None
    # the owner, from their own address, still signs in
    ok = await AuthService.login(db, "owner@example.com", "the-right-password-1",
                                 ip_address="198.51.100.4")
    assert ok and ok.get("token")


async def test_an_email_wide_cap_still_stops_a_distributed_guess(db):
    await _user(db, "target@example.com", "the-right-password-2")
    wide = get_settings().LOGIN_MAX_FAILURES * AuthService.EMAIL_WIDE_MULTIPLE
    for i in range(wide):
        await AuthService.login(db, "target@example.com", "wrong", ip_address=f"192.0.2.{i % 250}")
    assert await AuthService._is_locked_out("target@example.com", "198.51.100.77") is True


async def test_wrong_totp_codes_accumulate_until_lockout(db, monkeypatch):
    await _user(db, "mfa@example.com", "the-right-password-3")
    from app.services import mfa as mfa_svc

    async def enabled(_uid):
        return True

    async def wrong_code(_uid, _code):
        return False
    monkeypatch.setattr(mfa_svc, "is_enabled", enabled)
    monkeypatch.setattr(mfa_svc, "verify_login_code", wrong_code)
    n = get_settings().LOGIN_MAX_FAILURES
    for _ in range(n):
        out = await AuthService.login(db, "mfa@example.com", "the-right-password-3",
                                      ip_address="203.0.113.50", mfa_code="000000")
        assert out == {"mfa_required": True}
    # the right password no longer even reaches the code prompt from here
    assert await AuthService.login(db, "mfa@example.com", "the-right-password-3",
                                   ip_address="203.0.113.50", mfa_code="000000") is None


def _request(ip: str, tenant) -> Request:
    scope = {"type": "http", "method": "POST", "path": "/api/v1/auth/login", "headers": [],
             "client": (ip, 1234), "server": ("testserver", 80), "scheme": "http",
             "query_string": b"", "root_path": ""}
    req = Request(scope)
    req.state.tenant = tenant
    return req


def test_anonymous_requests_are_rate_limited_per_address(monkeypatch):
    from app.core.middleware import RateLimitMiddleware
    from app.core.tenant import _DEV_TENANT
    monkeypatch.setattr(get_settings(), "DEV_MODE", False)
    mw = RateLimitMiddleware(app=None)
    a = mw._caller_id(_request("203.0.113.1", _DEV_TENANT))
    b = mw._caller_id(_request("203.0.113.2", _DEV_TENANT))
    assert a != b and a.startswith("ip:")
    # an authenticated caller is still limited per tenant
    assert mw._caller_id(_request("203.0.113.1", {"tenant_id": "t1", "role": "viewer"})) == "t1"
