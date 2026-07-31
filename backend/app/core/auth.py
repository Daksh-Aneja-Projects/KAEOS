"""KAEOS — Authentication & API Key store (L17 Security Fabric).

DB-backed platform API keys. The previous module-global JSON dict meant a key
generated or revoked in one worker/replica was invisible to the others until a
restart — runtime revocation did not propagate. Every lookup and mutation now
goes through the ``api_keys`` table, so revocation is immediate fleet-wide.

The pre-auth lookup resolves the tenant FROM the key before any tenant context
exists, so it runs on the owner (maintenance) session — the same necessary
cross-tenant carve-out as email->tenant login.
"""
import logging
import hashlib
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import Request, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import select

logger = logging.getLogger(__name__)

security = HTTPBearer(auto_error=False)


def hash_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode()).hexdigest()


def _to_meta(k) -> dict:
    """Normalize an ApiKey row into the dict shape callers expect."""
    return {
        "tenant_id": k.tenant_id,
        "role": k.role,
        "name": k.name,
        "active": k.active,
        "rate_limit": k.rate_limit,
        "allowed_ips": k.allowed_ips or [],
        "allowed_origins": k.allowed_origins or [],
        "key_id": k.hashed_key[:12],
    }


async def get_api_key_by_hash(hashed: str) -> Optional[dict]:
    """Resolve a key by its hash (owner session; readable pre-tenant-context).

    Returns the normalized metadata dict, or None if the key is unknown. Revoked
    keys are returned too (with active=False) so callers can distinguish
    "unknown" from "revoked" for accurate error messages.
    """
    from app.core.database import MaintenanceSessionLocal
    from app.models.api_key import ApiKey
    async with MaintenanceSessionLocal() as db:
        row = (await db.execute(
            select(ApiKey).where(ApiKey.hashed_key == hashed)
        )).scalar_one_or_none()
    return _to_meta(row) if row else None


async def generate_api_key(tenant_id: str, name: str, role: str = "operator") -> dict:
    """Mint a new API key for a tenant and persist it. Returns the raw key ONCE."""
    from app.core.database import MaintenanceSessionLocal
    from app.models.api_key import ApiKey
    raw_key = f"kt_{uuid.uuid4().hex}"
    hashed = hash_key(raw_key)
    async with MaintenanceSessionLocal() as db:
        db.add(ApiKey(tenant_id=tenant_id, hashed_key=hashed, name=name, role=role))
        await db.commit()
    logger.info("[AUTH] Issued API key %s… for tenant=%s role=%s", hashed[:12], tenant_id, role)
    return {"api_key": raw_key, "key_id": hashed[:12], "tenant_id": tenant_id, "role": role}


async def list_api_keys(tenant_id: str) -> list[dict]:
    """All keys for one tenant (metadata only; the raw key is never recoverable)."""
    from app.core.database import MaintenanceSessionLocal
    from app.models.api_key import ApiKey
    async with MaintenanceSessionLocal() as db:
        rows = (await db.execute(
            select(ApiKey).where(ApiKey.tenant_id == tenant_id).order_by(ApiKey.created_at.desc())
        )).scalars().all()
    return [{
        "key_id": k.hashed_key[:12],
        "name": k.name,
        "role": k.role,
        "active": k.active,
        "created_at": k.created_at.isoformat() if k.created_at else None,
        "revoked_at": k.revoked_at.isoformat() if k.revoked_at else None,
    } for k in rows]


async def revoke_api_key(key_id_prefix: str, tenant_id: Optional[str] = None) -> bool:
    """Revoke a key by its id prefix. Propagates immediately (DB-backed).

    When ``tenant_id`` is given the revoke is scoped to that tenant, so a tenant
    admin can only revoke their OWN keys (the self-service route always passes
    it). The superadmin bootstrap path omits it for cross-tenant operation.
    """
    from app.core.database import MaintenanceSessionLocal
    from app.models.api_key import ApiKey
    async with MaintenanceSessionLocal() as db:
        conds = [ApiKey.hashed_key.like(f"{key_id_prefix}%"), ApiKey.active == True]  # noqa: E712
        if tenant_id is not None:
            conds.append(ApiKey.tenant_id == tenant_id)
        row = (await db.execute(select(ApiKey).where(*conds))).scalars().first()
        if not row:
            return False
        row.active = False
        row.revoked_at = datetime.now(timezone.utc)
        await db.commit()
    logger.info("[AUTH] Revoked API key %s…", key_id_prefix)
    return True


async def get_current_tenant(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> dict:
    """Extract tenant context from an API key (dev mode returns a default tenant)."""
    from app.core.config import get_settings
    if get_settings().DEV_MODE:
        return {"tenant_id": "tenant_acme", "role": "admin", "name": "dev_mode", "authenticated": False}

    if not credentials:
        raise HTTPException(401, "Missing API key. Use Authorization: Bearer kt_...")

    key_meta = await get_api_key_by_hash(hash_key(credentials.credentials))
    if not key_meta:
        raise HTTPException(401, "Invalid API key")
    if not key_meta.get("active", True):
        raise HTTPException(403, "API key has been revoked")

    return {
        "tenant_id": key_meta["tenant_id"],
        "role": key_meta["role"],
        "name": key_meta["name"],
        "authenticated": True,
    }


async def initialize_dev_mode():
    """Seed a default dev key if none exist and in DEV_MODE (best-effort)."""
    from app.core.config import get_settings
    if not get_settings().DEV_MODE:
        return
    from app.core.database import MaintenanceSessionLocal
    from app.models.api_key import ApiKey
    try:
        async with MaintenanceSessionLocal() as db:
            existing = (await db.execute(select(ApiKey).limit(1))).scalar_one_or_none()
        if existing is None:
            dev_key = await generate_api_key("tenant_acme", "dev_default", "admin")
            logger.info("[AUTH] Dev API key generated: %s… (truncated)", dev_key["api_key"][:8])
    except Exception as e:
        logger.warning("[AUTH] dev-key seed skipped: %s", e)
