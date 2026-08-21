"""KAEOS — SSO / OIDC service (real OpenID Connect Authorization Code flow).

This replaces the deleted mock middleware (which accepted a literal
``"mock_valid_jwt"``). Everything here is real:

  * discovery       — fetch the IdP's ``/.well-known/openid-configuration``;
  * authorize URL   — standard OIDC code-flow request with state + nonce;
  * code exchange    — POST the code to the token endpoint over TLS;
  * id_token verify  — RS256 signature via the IdP's JWKS, plus iss / aud / exp
                       / nonce checks (PyJWT does the crypto);
  * provisioning     — find-or-create the KAEOS user and mint a normal session.

State/nonce are carried in a short-lived HMAC-signed token (SECRET_KEY), so the
flow is stateless and correct under multiple workers — no shared session store
needed. The IdP client secret is stored Fernet-encrypted at rest and never
returned by the API.
"""
from __future__ import annotations

import logging
import secrets
from datetime import datetime, timezone, timedelta
from typing import Optional

import jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.outbound import guarded_async_client
from app.models.auth import User, UserRole
from app.models.sso import SSOConnection
from app.services.auth import _create_token  # session minting (single source of truth)
from app.services.live_connectors import encrypt_secrets, decrypt_secrets

logger = logging.getLogger(__name__)

_STATE_AUD = "kaeos-sso-state"
_STATE_TTL_MINUTES = 10
_HTTP_TIMEOUT = 10.0
# Small in-process cache of discovery docs keyed by issuer. TTL'd: endpoints are
# stable but not immortal — an IdP that rotates its jwks_uri used to stay wedged
# (auth broken) until a process restart.
_DISCOVERY_CACHE: dict[str, tuple[float, dict]] = {}   # issuer -> (fetched_at, doc)
_DISCOVERY_TTL_SECONDS = 3600


class SSOError(Exception):
    """Raised for any recoverable SSO configuration / protocol failure."""


# ── client-secret at rest ────────────────────────────────────────────────────

def encrypt_client_secret(secret: str) -> str:
    return encrypt_secrets({"client_secret": secret})


def decrypt_client_secret(token: Optional[str]) -> Optional[str]:
    if not token:
        return None
    return decrypt_secrets(token).get("client_secret")


# ── state (CSRF) + nonce, signed & stateless ─────────────────────────────────

def sign_state(tenant_id: str, nonce: str, return_to: Optional[str]) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "tid": tenant_id,
            "nonce": nonce,
            "rt": return_to or "",
            "aud": _STATE_AUD,
            "iat": now,
            "exp": now + timedelta(minutes=_STATE_TTL_MINUTES),
        },
        get_settings().SECRET_KEY,
        algorithm="HS256",
    )


def verify_state(state: str) -> dict:
    try:
        return jwt.decode(state, get_settings().SECRET_KEY, algorithms=["HS256"], audience=_STATE_AUD)
    except jwt.PyJWTError as e:
        raise SSOError("Invalid or expired SSO state") from e


# ── OIDC discovery + endpoints ───────────────────────────────────────────────

async def discover(issuer: str) -> dict:
    """Fetch (and cache) the IdP's OpenID discovery document."""
    import time
    issuer = issuer.rstrip("/")
    cached = _DISCOVERY_CACHE.get(issuer)
    if cached and time.time() - cached[0] < _DISCOVERY_TTL_SECONDS:
        return cached[1]
    url = f"{issuer}/.well-known/openid-configuration"
    async with guarded_async_client(timeout=_HTTP_TIMEOUT) as client:
        resp = await client.get(url)
    if resp.status_code != 200:
        # A stale doc beats a hard failure while the IdP hiccups: serve the
        # expired entry if one exists, so a transient discovery outage does not
        # take logins down with it.
        if cached:
            return cached[1]
        raise SSOError(f"OIDC discovery failed ({resp.status_code}) for {issuer}")
    doc = resp.json()
    for required in ("authorization_endpoint", "token_endpoint", "jwks_uri", "issuer"):
        if required not in doc:
            raise SSOError(f"OIDC discovery document missing '{required}'")
    _DISCOVERY_CACHE[issuer] = (time.time(), doc)
    return doc


def redirect_uri(request_base: str) -> str:
    """The callback URL registered at the IdP.

    Prefers the configured PUBLIC_BASE_URL (stable, matches IdP registration);
    falls back to the request origin for local dev.
    """
    settings = get_settings()
    base = (settings.PUBLIC_BASE_URL or request_base).rstrip("/")
    return f"{base}{settings.API_PREFIX}/auth/sso/oidc/callback"


def build_authorize_url(disc: dict, client_id: str, redirect: str, state: str, nonce: str) -> str:
    from urllib.parse import urlencode
    params = {
        "client_id": client_id,
        "response_type": "code",
        "scope": "openid email profile",
        "redirect_uri": redirect,
        "state": state,
        "nonce": nonce,
    }
    return f"{disc['authorization_endpoint']}?{urlencode(params)}"


async def exchange_code(disc: dict, conn: SSOConnection, code: str, redirect: str) -> str:
    """Exchange the authorization code for tokens; return the raw id_token."""
    client_secret = decrypt_client_secret(conn.client_secret_encrypted) or ""
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect,
        "client_id": conn.client_id,
        "client_secret": client_secret,
    }
    async with guarded_async_client(timeout=_HTTP_TIMEOUT) as client:
        resp = await client.post(disc["token_endpoint"], data=data,
                                 headers={"Accept": "application/json"})
    if resp.status_code != 200:
        raise SSOError(f"Token exchange failed ({resp.status_code})")
    body = resp.json()
    id_token = body.get("id_token")
    if not id_token:
        raise SSOError("Token response contained no id_token")
    return id_token


def verify_id_token(id_token: str, disc: dict, conn: SSOConnection, expected_nonce: str) -> dict:
    """Verify the id_token signature (RS256 via JWKS) and standard claims."""
    try:
        jwk_client = jwt.PyJWKClient(disc["jwks_uri"])
        signing_key = jwk_client.get_signing_key_from_jwt(id_token)
        claims = jwt.decode(
            id_token,
            signing_key.key,
            algorithms=["RS256"],
            audience=conn.client_id,
            issuer=disc["issuer"],
        )
    except jwt.PyJWTError as e:
        raise SSOError(f"id_token verification failed: {e}") from e
    if claims.get("nonce") != expected_nonce:
        raise SSOError("id_token nonce mismatch (possible replay)")
    if not claims.get("email"):
        raise SSOError("id_token has no email claim; cannot map to a KAEOS user")
    return claims


# ── connection lookup ─────────────────────────────────────────────────────────

async def get_connection(db: AsyncSession, tenant_id: str, protocol: str = "OIDC") -> Optional[SSOConnection]:
    row = await db.execute(
        select(SSOConnection).where(
            SSOConnection.tenant_id == tenant_id,
            SSOConnection.protocol == protocol,
            SSOConnection.is_enabled == True,  # noqa: E712
        )
    )
    return row.scalar_one_or_none()


async def connection_for_email(email: str) -> Optional[SSOConnection]:
    """Resolve which tenant/IdP an email address should authenticate against.

    Uses the maintenance (owner) session so the pre-auth discovery lookup can see
    across tenants by email domain — the same necessary-cross-tenant carve-out
    login already has (a user cannot know their tenant before authenticating).
    """
    domain = (email or "").split("@")[-1].strip().lower()
    if not domain:
        return None
    from app.core.database import MaintenanceSessionLocal
    async with MaintenanceSessionLocal() as owner:
        row = await owner.execute(
            select(SSOConnection).where(
                SSOConnection.email_domain == domain,
                SSOConnection.is_enabled == True,  # noqa: E712
                # Only a VERIFIED domain routes logins: an unverified (possibly
                # squatted) claim must never send a victim's users to it.
                SSOConnection.domain_verified == True,  # noqa: E712
            ).order_by(SSOConnection.created_at.asc())
        )
        # .first(), not scalar_one_or_none(): even with the partial-unique index a
        # race could momentarily leave two verified rows, and a 500 on the login
        # discovery path is itself a denial of service. Take the earliest.
        return row.scalars().first()


def _resolve_txt(name: str) -> list[str]:
    """TXT records for a DNS name. Isolated in one function so tests monkeypatch
    it instead of hitting real DNS; fail-closed (empty) on any resolver error."""
    try:
        import dns.resolver
        answers = dns.resolver.resolve(name, "TXT", lifetime=5.0)
    except Exception:
        return []
    out = []
    for rdata in answers:
        try:
            out.append(b"".join(rdata.strings).decode("utf-8", "ignore"))
        except Exception:
            out.append(str(rdata).strip('"'))
    return out


_CHALLENGE_HOST = "_kaeos-challenge"
_CHALLENGE_PREFIX = "kaeos-domain-verification="


async def verify_domain(connection_id: str, tenant_id: str) -> dict:
    """Prove the tenant controls its SSO email_domain via a DNS TXT record at
    ``_kaeos-challenge.<domain>`` holding ``kaeos-domain-verification=<token>``.

    Fail-closed: any DNS/resolver error is a non-verification. A domain already
    verified by ANOTHER tenant cannot be taken over.
    """
    from app.core.database import MaintenanceSessionLocal
    async with MaintenanceSessionLocal() as owner:
        conn = (await owner.execute(select(SSOConnection).where(
            SSOConnection.id == connection_id,
            SSOConnection.tenant_id == tenant_id,
        ))).scalar_one_or_none()
        if conn is None:
            return {"verified": False, "error": "connection_not_found"}
        domain = (conn.email_domain or "").strip().lower()
        if not domain:
            return {"verified": False, "error": "no_domain_set"}
        if not conn.domain_verification_token:
            return {"verified": False, "error": "no_challenge_issued"}
        other = (await owner.execute(select(SSOConnection).where(
            SSOConnection.email_domain == domain,
            SSOConnection.domain_verified == True,  # noqa: E712
            SSOConnection.tenant_id != tenant_id,
        ))).first()
        if other is not None:
            return {"verified": False, "error": "domain_claimed_by_another_tenant"}
        want = _CHALLENGE_PREFIX + conn.domain_verification_token
        records = _resolve_txt(f"{_CHALLENGE_HOST}.{domain}")
        if want not in records:
            return {"verified": False, "error": "txt_record_not_found",
                    "add_dns_txt": {"name": f"{_CHALLENGE_HOST}.{domain}", "value": want}}
        conn.domain_verified = True
        await owner.commit()
        return {"verified": True, "domain": domain}


# ── provisioning + session mint ───────────────────────────────────────────────

def _role_from(value: str) -> UserRole:
    try:
        return UserRole(value)
    except ValueError:
        return UserRole.VIEWER


async def provision_and_login(db: AsyncSession, tenant_id: str, claims: dict,
                              default_role: str) -> dict:
    """Find-or-JIT-provision the SSO user, then mint a normal KAEOS session.

    The provisioned account has an unusable random password hash, so it can only
    ever be accessed via SSO — never via ``/auth/login``.
    """
    email = claims["email"].strip().lower()
    display_name = claims.get("name") or claims.get("preferred_username") or email

    existing = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if existing:
        if not existing.is_active:
            raise SSOError("Account is deactivated")
        user = existing
    else:
        # Unusable password: a random secret that is hashed but never disclosed.
        from app.services.auth import _hash_password
        user = User(
            email=email,
            display_name=display_name,
            hashed_password=await _hash_password(secrets.token_urlsafe(32)),
            role=_role_from(default_role),
            tenant_id=tenant_id,
            is_active=True,
        )
        db.add(user)
        await db.flush()
        logger.info("[SSO] JIT-provisioned user %s (tenant=%s, role=%s)",
                    email, tenant_id, user.role.value)

    user.login_count = (user.login_count or 0) + 1
    user.last_login_at = datetime.now(timezone.utc)
    await db.commit()

    token = _create_token(user.id, user.email, user.role.value, user.tenant_id)
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "id": user.id,
            "email": user.email,
            "display_name": user.display_name,
            "role": user.role.value,
            "tenant_id": user.tenant_id,
        },
    }
