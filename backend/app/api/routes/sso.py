"""KAEOS — SSO / OIDC routes.

Public (pre-auth) endpoints drive the OpenID Connect Authorization Code flow;
admin endpoints are the Settings -> Security config surface for managing a
tenant's IdP connection. The public paths are exempted from tenant auth in
``app/core/tenant.py`` (like ``/auth/login``); the admin paths require ADMIN.
"""
import logging
import secrets
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db, MaintenanceSessionLocal
from app.core.tenant import get_tenant_id
from app.core.entitlements import require_entitlement
from app.models.sso import SSOConnection
from app.api.routes.auth import require_role
from app.services import sso as sso_svc
from app.services import saml as saml_svc

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth/sso", tags=["Authentication — SSO/OIDC"])


def _safe_return_to(return_to: Optional[str]) -> str:
    """The freshly minted session token is handed back in the redirect fragment,
    so return_to MUST NOT be an attacker-controlled host (open redirect ->
    token theft -> account takeover). Allow only a site-relative path or an
    absolute URL whose origin is explicitly allowlisted in CORS_ORIGINS; anything
    else falls back to the app root (token still delivered, same-origin)."""
    from urllib.parse import urlparse
    if not return_to:
        return "/"
    if return_to.startswith("/") and not return_to.startswith("//"):
        return return_to   # site-relative (but not protocol-relative //evil.com)
    try:
        p = urlparse(return_to)
    except Exception:
        return "/"
    if p.scheme in ("http", "https") and p.netloc:
        from app.core.config import get_settings
        allowed = {o.rstrip("/") for o in (getattr(get_settings(), "CORS_ORIGINS", []) or [])}
        if f"{p.scheme}://{p.netloc}" in allowed:
            return return_to
    return "/"


# ── public: discovery for the login page ──────────────────────────────────────

@router.get("/discover")
async def discover_sso(email: str):
    """Given an email, report whether SSO is configured for its domain.

    The login page calls this to decide between password and 'Continue with SSO'.
    """
    conn = await sso_svc.connection_for_email(email)  # owner-session lookup inside
    if not conn:
        return {"sso": False}
    if conn.protocol == "SAML":
        authorize_url = f"/api/v1/auth/sso/saml/login?tenant_id={conn.tenant_id}"
    else:
        authorize_url = f"/api/v1/auth/sso/oidc/authorize?tenant_id={conn.tenant_id}"
    return {
        "sso": True,
        "protocol": conn.protocol,
        "provider_label": conn.provider_label,
        "tenant_id": conn.tenant_id,
        "authorize_url": authorize_url,
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
        safe_rt = _safe_return_to(return_to)   # refuse open redirect -> token theft
        sep = "&" if "#" in safe_rt else "#"
        return RedirectResponse(f"{safe_rt}{sep}token={result['access_token']}", status_code=302)
    return result


# ── public: SAML 2.0 SP-initiated flow ────────────────────────────────────────

@router.get("/saml/metadata", response_class=Response)
async def saml_metadata(request: Request):
    """SP metadata XML - hand this to the IdP administrator."""
    return Response(content=saml_svc.sp_metadata(str(request.base_url)),
                    media_type="application/samlmetadata+xml")


@router.get("/saml/login")
async def saml_login(request: Request, tenant_id: Optional[str] = None,
                     email: Optional[str] = None, return_to: Optional[str] = None):
    """Begin SAML login: redirect the browser to the tenant's IdP with an AuthnRequest."""
    if email and not tenant_id:
        conn = await sso_svc.connection_for_email(email)
    elif tenant_id:
        async with MaintenanceSessionLocal() as owner:
            conn = await sso_svc.get_connection(owner, tenant_id, protocol="SAML")
    else:
        raise HTTPException(status_code=400, detail="tenant_id or email is required")

    if not conn or conn.protocol != "SAML":
        raise HTTPException(status_code=404, detail="No SAML connection configured")

    try:
        # RelayState carries the signed state; its `nonce` slot holds the
        # AuthnRequest ID so the ACS can enforce InResponseTo statelessly.
        request_id = saml_svc.new_request_id()
        relay = sso_svc.sign_state(conn.tenant_id, request_id, return_to)
        url = saml_svc.build_authn_request(conn, str(request.base_url), relay, request_id)
    except sso_svc.SSOError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return RedirectResponse(url, status_code=302)


@router.post("/saml/acs")
async def saml_acs(request: Request,
                   SAMLResponse: str = Form(...),           # noqa: N803 - the SAML wire name
                   RelayState: Optional[str] = Form(None)):  # noqa: N803
    """Assertion Consumer Service: verify the IdP's signed assertion, mint a session."""
    if not RelayState:
        raise HTTPException(status_code=400, detail="Missing RelayState")
    try:
        st = sso_svc.verify_state(RelayState)
    except sso_svc.SSOError as e:
        raise HTTPException(status_code=400, detail=str(e))
    tenant_id, request_id, return_to = st["tid"], st.get("nonce") or None, st.get("rt") or ""

    async with MaintenanceSessionLocal() as owner:
        conn = await sso_svc.get_connection(owner, tenant_id, protocol="SAML")
        if not conn:
            raise HTTPException(status_code=404, detail="SAML connection no longer exists")
        try:
            claims = saml_svc.verify_response(SAMLResponse, conn, str(request.base_url), request_id)
            await saml_svc.claim_assertion_id(claims["assertion_id"])
            result = await sso_svc.provision_and_login(owner, tenant_id, claims, conn.default_role)
        except sso_svc.SSOError as e:
            logger.warning("[SAML] ACS rejected an assertion for tenant=%s: %s", tenant_id, e)
            raise HTTPException(status_code=401, detail=str(e))

    # Same hand-back contract as OIDC: fragment, never the query string.
    if return_to:
        safe_rt = _safe_return_to(return_to)   # refuse open redirect -> token theft
        sep = "&" if "#" in safe_rt else "#"
        return RedirectResponse(f"{safe_rt}{sep}token={result['access_token']}", status_code=302)
    return result


# ── admin: Settings -> Security config surface ────────────────────────────────

class SSOConnectionIn(BaseModel):
    protocol: str = "OIDC"
    provider_label: str = ""
    issuer: str
    client_id: str = ""                   # OIDC only
    client_secret: Optional[str] = None   # write-only; omitted on update keeps the stored one
    idp_sso_url: Optional[str] = None     # SAML only
    idp_x509_cert: Optional[str] = None   # SAML only
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
        "idp_sso_url": conn.idp_sso_url,
        "idp_x509_cert_set": bool(conn.idp_x509_cert),
        "email_domain": conn.email_domain,
        "domain_verified": conn.domain_verified,
        # The DNS TXT record the tenant admin must publish to verify the domain
        # (only meaningful while unverified). Not a credential.
        "domain_challenge": (
            {"name": f"{sso_svc._CHALLENGE_HOST}.{conn.email_domain}",
             "value": sso_svc._CHALLENGE_PREFIX + conn.domain_verification_token}
            if conn.email_domain and conn.domain_verification_token and not conn.domain_verified
            else None
        ),
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


@router.post("/connections", dependencies=[Depends(require_entitlement("sso"))])
async def upsert_connection(data: SSOConnectionIn,
                            user: dict = Depends(require_role("ADMIN")),
                            tenant_id: str = Depends(get_tenant_id),
                            db: AsyncSession = Depends(get_db)):
    """Create or update this tenant's IdP connection (one per protocol)."""
    if data.protocol not in ("OIDC", "SAML"):
        raise HTTPException(status_code=400, detail="protocol must be OIDC or SAML")
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
    conn.issuer = data.issuer.rstrip("/")   # OIDC issuer URL / SAML IdP EntityID
    # A new or changed email_domain is UNVERIFIED until the tenant proves control
    # (DNS TXT challenge); it does not route logins until then. Issue a token.
    new_domain = (data.email_domain or "").strip().lower() or None
    if new_domain != conn.email_domain:
        conn.email_domain = new_domain
        conn.domain_verified = False
        conn.domain_verification_token = secrets.token_hex(16) if new_domain else None
    elif new_domain and not conn.domain_verification_token:
        conn.domain_verification_token = secrets.token_hex(16)
    conn.default_role = data.default_role
    conn.is_enabled = data.is_enabled

    if data.protocol == "OIDC":
        conn.client_id = data.client_id
        if data.client_secret:
            conn.client_secret_encrypted = sso_svc.encrypt_client_secret(data.client_secret)
        elif existing is None:
            raise HTTPException(status_code=400, detail="client_secret is required to create an OIDC connection")
    else:  # SAML
        if data.idp_sso_url:
            conn.idp_sso_url = data.idp_sso_url.strip()
        if data.idp_x509_cert:
            conn.idp_x509_cert = data.idp_x509_cert.strip()
        if existing is None and (not conn.idp_sso_url or not conn.idp_x509_cert):
            raise HTTPException(
                status_code=400,
                detail="idp_sso_url and idp_x509_cert are required to create a SAML connection",
            )

    if existing is None:
        db.add(conn)
    await db.commit()
    await db.refresh(conn)
    return _serialize(conn)


@router.post("/connections/{connection_id}/verify-domain")
async def verify_connection_domain(connection_id: str,
                                   user: dict = Depends(require_role("ADMIN")),
                                   tenant_id: str = Depends(get_tenant_id)):
    """Verify this tenant controls its SSO email_domain via the DNS TXT challenge.
    Until verified the domain does not route logins, so a squatted claim is inert."""
    result = await sso_svc.verify_domain(connection_id, tenant_id)
    if not result.get("verified"):
        code = 409 if result.get("error") == "domain_claimed_by_another_tenant" else 400
        raise HTTPException(status_code=code, detail=result)
    return result


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
