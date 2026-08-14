"""MFA / TOTP — RFC 6238 correctness + enroll/confirm/login-gate flow."""
import pytest

from app.services import mfa
from app.core.database import engine as app_engine
from app.models.mfa import UserMFA


U = "user_mfa_1"
T = "tenant_mfa"


@pytest.fixture(autouse=True)
async def _mfa_table():
    # The TOTP secret is now encrypted under a per-tenant data key, so the
    # enroll/confirm/login flow reads+writes tenant_data_keys on the app engine.
    from app.models.tenant_data_key import TenantDataKey
    async with app_engine.begin() as conn:
        await conn.run_sync(UserMFA.__table__.create, checkfirst=True)
        await conn.run_sync(TenantDataKey.__table__.create, checkfirst=True)
        from sqlalchemy import text
        await conn.execute(text("DELETE FROM user_mfa"))
        await conn.execute(text("DELETE FROM tenant_data_keys"))
    yield
    async with app_engine.begin() as conn:
        from sqlalchemy import text
        await conn.execute(text("DELETE FROM user_mfa"))
        await conn.execute(text("DELETE FROM tenant_data_keys"))


# ── pure TOTP ─────────────────────────────────────────────────────────────────

def test_totp_verifies_current_code_and_rejects_others():
    secret = mfa.generate_secret()
    t = 1_700_000_000.0
    code = mfa.totp_now(secret, at=t)
    assert mfa.verify_code(secret, code, at=t) is True
    assert mfa.verify_code(secret, code, at=t + 30) is True          # within +/-1 window
    assert mfa.verify_code(secret, code, at=t + 120) is False        # far outside window
    assert mfa.verify_code(secret, "000000", at=t) is False          # wrong code
    assert mfa.verify_code(secret, "", at=t) is False


def test_provisioning_uri_is_otpauth():
    uri = mfa.provisioning_uri("ABCDEFGH", "alice@corp.com")
    assert uri.startswith("otpauth://totp/")
    assert "secret=ABCDEFGH" in uri


# ── enroll -> confirm -> login gate ───────────────────────────────────────────

async def test_enroll_confirm_and_login_gate():
    assert (await mfa.status(U))["enabled"] is False

    enroll = await mfa.begin_enrollment(U, T, account="alice@corp.com")
    secret = enroll["secret"]
    assert enroll["otpauth_uri"].startswith("otpauth://")

    # Not enabled until a code is confirmed.
    assert (await mfa.status(U)) == {"enrolled": True, "enabled": False}
    assert await mfa.verify_login_code(U, "123456") is True   # not enabled -> gate is open

    # Wrong code does not enable.
    assert (await mfa.confirm_enrollment(U, "000000")).get("error") == "invalid_code"

    # Correct code enables MFA (and consumes that time-step).
    assert (await mfa.confirm_enrollment(U, mfa.totp_now(secret)))["enabled"] is True
    assert await mfa.is_enabled(U) is True

    # Replay guard: the code that confirmed enrollment cannot be reused at login.
    assert await mfa.verify_login_code(U, mfa.totp_now(secret)) is False

    # A code from the next time-step is accepted once, then rejected on reuse.
    import time as _t
    nxt = mfa.totp_now(secret, at=_t.time() + 30)
    assert await mfa.verify_login_code(U, nxt) is True
    assert await mfa.verify_login_code(U, nxt) is False   # replay of the same step
    assert await mfa.verify_login_code(U, "000000") is False

    # Disable removes the requirement.
    await mfa.disable(U)
    assert await mfa.is_enabled(U) is False
    assert await mfa.verify_login_code(U, "anything") is True


async def test_confirm_without_enrollment_errors():
    assert (await mfa.confirm_enrollment("nobody", "123456")).get("error") == "no_enrollment"
