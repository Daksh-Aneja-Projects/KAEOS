"""KAEOS — MFA (TOTP) service.

RFC 6238 TOTP implemented with the standard library (hmac/hashlib/base64) — no
extra dependency. Secrets are stored Fernet-encrypted at rest and never returned
after enrollment. Enroll -> confirm (proves the authenticator is set up) -> the
second factor is then required at login.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
import urllib.parse
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select

from app.services.live_connectors import encrypt_secrets, decrypt_secrets

_DIGITS = 6
_PERIOD = 30
_DEFAULT_WINDOW = 1   # tolerate +/- one 30s step for clock skew


# ── TOTP primitives (RFC 6238 / 4226) ─────────────────────────────────────────

def generate_secret() -> str:
    """A fresh base32 TOTP secret (160 bits)."""
    return base64.b32encode(secrets.token_bytes(20)).decode("utf-8").rstrip("=")


def _hotp(secret_b32: str, counter: int) -> str:
    key = base64.b32decode(secret_b32 + "=" * (-len(secret_b32) % 8), casefold=True)
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = (struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF) % (10 ** _DIGITS)
    return str(code).zfill(_DIGITS)


def totp_now(secret_b32: str, at: Optional[float] = None) -> str:
    counter = int((at if at is not None else time.time()) // _PERIOD)
    return _hotp(secret_b32, counter)


def verify_code(secret_b32: str, code: str, *, window: int = _DEFAULT_WINDOW,
                at: Optional[float] = None) -> bool:
    if not code or not str(code).strip().isdigit():
        return False
    code = str(code).strip()
    counter = int((at if at is not None else time.time()) // _PERIOD)
    for w in range(-window, window + 1):
        if hmac.compare_digest(_hotp(secret_b32, counter + w), code):
            return True
    return False


def provisioning_uri(secret_b32: str, account: str, issuer: str = "KAEOS") -> str:
    """otpauth:// URI an authenticator app / QR code consumes."""
    label = urllib.parse.quote(f"{issuer}:{account}")
    params = urllib.parse.urlencode({
        "secret": secret_b32, "issuer": issuer, "digits": _DIGITS, "period": _PERIOD,
    })
    return f"otpauth://totp/{label}?{params}"


# ── enrollment / verification (owner session: pre-context safe) ───────────────

async def _row(db, user_id: str):
    from app.models.mfa import UserMFA
    return (await db.execute(select(UserMFA).where(UserMFA.user_id == user_id))).scalar_one_or_none()


async def begin_enrollment(user_id: str, tenant_id: str, account: str) -> dict:
    """Create (or reset) a pending MFA secret. Returns the secret + otpauth URI ONCE."""
    from app.core.database import MaintenanceSessionLocal
    from app.models.mfa import UserMFA
    secret = generate_secret()
    async with MaintenanceSessionLocal() as db:
        row = await _row(db, user_id)
        if row is None:
            row = UserMFA(user_id=user_id, tenant_id=tenant_id,
                          secret_encrypted=encrypt_secrets({"s": secret}), enabled=False)
            db.add(row)
        else:
            row.secret_encrypted = encrypt_secrets({"s": secret})
            row.enabled = False
            row.confirmed_at = None
        await db.commit()
    return {"secret": secret, "otpauth_uri": provisioning_uri(secret, account)}


async def confirm_enrollment(user_id: str, code: str) -> dict:
    """Verify the first code, proving the authenticator works, then enable MFA."""
    from app.core.database import MaintenanceSessionLocal
    async with MaintenanceSessionLocal() as db:
        row = await _row(db, user_id)
        if row is None:
            return {"error": "no_enrollment"}
        secret = decrypt_secrets(row.secret_encrypted).get("s", "")
        if not verify_code(secret, code):
            return {"error": "invalid_code"}
        row.enabled = True
        row.confirmed_at = datetime.now(timezone.utc)
        await db.commit()
    return {"enabled": True}


async def disable(user_id: str) -> dict:
    from app.core.database import MaintenanceSessionLocal
    async with MaintenanceSessionLocal() as db:
        row = await _row(db, user_id)
        if row is not None:
            await db.delete(row)
            await db.commit()
    return {"enabled": False}


async def status(user_id: str) -> dict:
    from app.core.database import MaintenanceSessionLocal
    async with MaintenanceSessionLocal() as db:
        row = await _row(db, user_id)
    return {"enrolled": row is not None, "enabled": bool(row and row.enabled)}


async def is_enabled(user_id: str) -> bool:
    return (await status(user_id))["enabled"]


async def verify_login_code(user_id: str, code: str) -> bool:
    """Second-factor check at login (owner session — runs before tenant context)."""
    from app.core.database import MaintenanceSessionLocal
    async with MaintenanceSessionLocal() as db:
        row = await _row(db, user_id)
    if row is None or not row.enabled:
        return True   # MFA not enabled for this user — nothing to check
    secret = decrypt_secrets(row.secret_encrypted).get("s", "")
    return verify_code(secret, code)
