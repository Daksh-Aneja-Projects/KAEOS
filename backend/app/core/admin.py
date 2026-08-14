"""
Platform-admin authorization.

Some operations are legitimately CROSS-TENANT — provisioning a new tenant,
listing every tenant's onboarding, bootstrapping API keys. Tenant JWTs must not
authorize those: a customer's token proves who they are, not that they may act
on the platform. They are gated on a configured ADMIN_SECRET instead.

Lives here, not in main.py, so route modules can import the guard without a
circular import back through the app object.
"""
import secrets as _secrets
from typing import Optional

from fastapi import Header, HTTPException

from app.core.config import get_settings


def verify_admin_secret(x_admin_secret: Optional[str]) -> None:
    """Authorize a platform-admin action, or raise.

    503 when ADMIN_SECRET is unset: the endpoint is DISABLED rather than
    falling back to a shared default (a default admin secret is the same as no
    admin secret). 403 when a secret is supplied but wrong. Compared in
    constant time so a wrong secret leaks nothing through timing.
    """
    admin_secret = getattr(get_settings(), "ADMIN_SECRET", "") or ""
    if not admin_secret:
        raise HTTPException(
            status_code=503,
            detail="Admin operations are disabled: ADMIN_SECRET is not configured.",
        )
    if not x_admin_secret or not _secrets.compare_digest(x_admin_secret, admin_secret):
        raise HTTPException(status_code=403, detail="Invalid admin secret")


def require_superadmin(x_admin_secret: Optional[str] = Header(None)) -> None:
    """FastAPI dependency: gate a route behind platform super-admin.

    Thin wrapper over verify_admin_secret so cross-tenant operator routes can
    declare ``dependencies=[Depends(require_superadmin)]`` instead of repeating
    the Header+verify dance. Same gate as the existing /tenants/stats and
    /admin/security/api-keys surfaces (the ADMIN_SECRET), not a new authority:
    a tenant JWT proves who a customer is, never that they may act platform-wide.
    Fails closed — 503 when ADMIN_SECRET is unconfigured, 403 when wrong.
    """
    verify_admin_secret(x_admin_secret)


def is_admin(x_admin_secret: Optional[str]) -> bool:
    """True when a VALID admin secret was supplied. Never raises.

    For endpoints that serve both roles: a tenant sees its own record, a
    platform admin sees everyone's. Absence of a secret is an ordinary tenant
    call, not an error.
    """
    if not x_admin_secret:
        return False
    admin_secret = getattr(get_settings(), "ADMIN_SECRET", "") or ""
    if not admin_secret:
        return False
    return _secrets.compare_digest(x_admin_secret, admin_secret)
