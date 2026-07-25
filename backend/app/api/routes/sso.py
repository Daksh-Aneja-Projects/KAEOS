"""KAEOS — SSO / OIDC routes.

Public (pre-auth) endpoints drive the OpenID Connect Authorization Code flow;
admin endpoints are the Settings -> Security config surface for managing a
tenant's IdP connection. The public paths are exempted from tenant auth in
``app/core/tenant.py`` (like ``/auth/login``); the admin paths require ADMIN.
"""
import logging
import secrets
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db, MaintenanceSessionLocal
from app.core.tenant import get_tenant_id
from app.models.sso import SSOConnection
from app.api.routes.auth import require_role
from app.services import sso as sso_svc

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth/sso", tags=["Authentication — SSO/OIDC"])


# ── public: discovery for the login page ──────────────────────────────────────

@router.get("/discover")
async def discover_sso(email: str):
    """Given an email, report whether SSO is configured for its domain.

    The login page calls this to decide between password and 'Continue with SSO'.
    """
    conn = await sso_svc.connection_for_email(email)  # owner-session lookup inside
    if not conn:
        return {"sso": False}
    return {
        "sso": True,
        "protocol": conn.protocol,
        "provider_label": conn.provider_label,
        "tenant_id": conn.tenant_id,
        "authorize_url": f"/api/v1/auth/sso/oidc/authorize?tenant_id={conn.tenant_id}",
    }


# ── public: OIDC authorization-code flow ──────────────────────────────────────

@router.get("/oidc/authorize")
async def oidc_authorize(request: Request, tenant_id: Optional[str] = None,
                         email: Optional[str] = None, return_to: Optional[str] = None):
    """Begin OIDC login: redirect the browser to the IdP's authorization endpoint."""
    if email and not tenant_id:
        conn = await sso_svc.connection_for_email(email)
    elif tenant_id:
        async with MaintenanceSessionLocal() as owner:
            conn = await sso_svc.get_connection(owner, tenant_id)
    else:
        raise HTTPException(status_code=400, detail="tenant_id or email is required")

    if not conn or conn.protocol != "OIDC":
        raise HTTPException(status_code=404, detail="No OIDC connection configured")

    try:
        disc = await sso_svc.discover(conn.issuer)
    except sso_svc.SSOError as e:
        raise HTTPException(status_code=502, detail=str(e))

    nonce = secrets.token_urlsafe(16)
    state = sso_svc.sign_state(conn.tenant_id, nonce, return_to)
    redirect = sso_svc.redirect_uri(str(request.base_url))
    url = sso_svc.build_authorize_url(disc, conn.client_id, redirect, state, nonce)
    return RedirectResponse(url, status_code=302)


@router.get("/oidc/callback")
async def oidc_callback(request: Request, code: Optional[str] = None,
                        state: Optional[str] = None, error: Optional[str] = None,
                        error_description: Optional[str] = None):
    """IdP redirect target: exchange the code, verify the id_token, mint a session."""
    if error:
        raise HTTPException(status_code=401, detail=f"IdP error: {error} {error_description or ''}".strip())
    if not code or not state:
        raise HTTPException(status_code=400, detail="Missing code or state")

    try:
        st = sso_svc.verify_state(state)
    except sso_svc.SSOError as e:
        raise HTTPException(status_code=400, detail=str(e))
    tenant_id, nonce, return_to = st["tid"], st["nonce"], st.get("rt") or ""

    async with MaintenanceSessionLocal() as owner:
        conn = await sso_svc.get_connection(owner, tenant_id)
        if not conn:
            raise HTTPException(status_code=404, detail="OIDC connection no longer exists")
        try:
            disc = await sso_svc.discover(conn.issuer)
            redirect = sso_svc.redirect_uri(str(request.base_url))
            id_token = await sso_svc.exchange_code(disc, conn, code, redirect)
            claims = sso_svc.verify_id_token(id_token, disc, conn, nonce)
            result = await sso_svc.provision_and_login(owner, tenant_id, claims, conn.default_role)
        except sso_svc.SSOError as e:
            logger.warning("[SSO] callback failed for tenant=%s: %s", tenant_id, e)
            raise HTTPException(status_code=401, detail=str(e))

    # If the SPA gave a return target, hand the session back via the URL fragment
    # (never the query string — fragments are not logged/forwarded). Otherwise
    # return JSON for API clients and tests.
    if return_to:
        sep = "&" if "#" in return_to else "#"
        return RedirectResponse(f"{return_to}{sep}token={result['access_token']}", status_code=302)
    return result


# ── admin: Settings -> Security config surface ────────────────────────────────

class SSOConnectionIn(BaseModel):
    protocol: str = "OIDC"
    provider_label: str = ""
    issuer: str
    client_id: str
    client_secret: Optional[str] = None   # write-only; omitted on update keeps the stored one
    email_domain: Optional[str] = None
    default_role: str = "VIEWER"
    is_enabled: bool = True


def _serialize(conn: SSOConnection) -> dict:
    """Never leak the secret; report only whether one is configured."""
    return {
        "id": conn.id,
        "tenant_id": conn.tenant_id,
        "protocol": conn.protocol,
        "provider_label": conn.provider_label,
        "issuer": conn.issuer,
        "client_id": conn.client_id,
        "client_secret_set": bool(conn.client_secret_encrypted),
        "email_domain": conn.email_domain,
        "default_role": conn.default_role,
        "is_enabled": conn.is_enabled,
    }


@router.get("/connections")
async def list_connections(user: dict = Depends(require_role("ADMIN")),
                           tenant_id: str = Depends(get_tenant_id),
                           db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(
        select(SSOConnection).where(SSOConnection.tenant_id == tenant_id)
    )).scalars().all()
    return {"connections": [_serialize(c) for c in rows]}


@router.post("/connections")
async def upsert_connection(data: SSOConnectionIn,
                            user: dict = Depends(require_role("ADMIN")),
                            tenant_id: str = Depends(get_tenant_id),
                            db: AsyncSession = Depends(get_db)):
    """Create or update this tenant's IdP connection (one per protocol)."""
    if data.protocol not in ("OIDC", "SAML"):
        raise HTTPException(status_code=400, detail="protocol must be OIDC or SAML")
    if data.protocol == "SAML":
        raise HTTPException(status_code=501, detail="SAML is not yet implemented; use OIDC.")
    if data.default_role not in ("ADMIN", "ANALYST", "VIEWER"):
        raise HTTPException(status_code=400, detail="default_role must be ADMIN, ANALYST or VIEWER")

    existing = (await db.execute(
        select(SSOConnection).where(
            SSOConnection.tenant_id == tenant_id,
            SSOConnection.protocol == data.protocol,
        )
    )).scalar_one_or_none()

    conn = existing or SSOConnection(tenant_id=tenant_id, protocol=data.protocol)
    conn.provider_label = data.provider_label
    conn.issuer = data.issuer.rstrip("/")
    conn.client_id = data.client_id
    conn.email_domain = (data.email_domain or "").strip().lower() or None
    conn.default_role = data.default_role
    conn.is_enabled = data.is_enabled
    if data.client_secret:
        conn.client_secret_encrypted = sso_svc.encrypt_client_secret(data.client_secret)
    elif existing is None:
        raise HTTPException(status_code=400, detail="client_secret is required to create a connection")

    if existing is None:
        db.add(conn)
    await db.commit()
    await db.refresh(conn)
    return _serialize(conn)


@router.delete("/connections/{conn_id}")
async def delete_connection(conn_id: str,
                            user: dict = Depends(require_role("ADMIN")),
                            tenant_id: str = Depends(get_tenant_id),
                            db: AsyncSession = Depends(get_db)):
    conn = (await db.execute(
        select(SSOConnection).where(
            SSOConnection.id == conn_id, SSOConnection.tenant_id == tenant_id
        )
    )).scalar_one_or_none()
    if not conn:
        raise HTTPException(status_code=404, detail="Connection not found")
    await db.delete(conn)
    await db.commit()
    return {"deleted": conn_id}
