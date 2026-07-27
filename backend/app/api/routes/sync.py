"""Bidirectional sync API - realtime inbound ingest + outbound write-back ops.

The ingest endpoint is PUBLIC (external systems cannot hold KAEOS JWTs); each
request is authenticated by an HMAC-SHA256 signature over the raw body using
the connector's webhook_secret. Everything else is operator/admin-gated.
"""
import secrets as pysecrets
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.tenant import get_tenant_id, require_role

router = APIRouter(prefix="/integrations", tags=["Integrations Sync"])


@router.post("/ingest/{connector_id}")
async def ingest(connector_id: str, request: Request,
                 x_kaeos_signature: Optional[str] = Header(None)):
    """Realtime inbound: an external system pushes a change the moment it
    happens. HMAC-authenticated; the connector row resolves the tenant."""
    from app.services.sync_engine import ingest_webhook
    raw = await request.body()
    try:
        return await ingest_webhook(connector_id, x_kaeos_signature, raw)
    except LookupError:
        raise HTTPException(status_code=404, detail="connector not found")
    except PermissionError:
        raise HTTPException(status_code=401, detail="invalid webhook signature")


@router.post("/ingest/{connector_id}/security")
async def ingest_security_event(connector_id: str, request: Request,
                                x_kaeos_signature: Optional[str] = Header(None)):
    """SOAR intake: an integrated app reports a security event (breach,
    credential leak, anomalous access, malware). KAEOS records a real Incident
    and runs the governed containment playbook. Same HMAC auth as sync ingest."""
    from app.services.security_response import respond_to_security_event
    raw = await request.body()
    try:
        return await respond_to_security_event(connector_id, x_kaeos_signature, raw)
    except LookupError:
        raise HTTPException(status_code=404, detail="connector not found")
    except PermissionError:
        raise HTTPException(status_code=401, detail="invalid webhook signature")


@router.post("/{connector_id}/webhook-secret")
async def mint_webhook_secret(
    connector_id: str,
    tenant: dict = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """Mint (or rotate) the connector's inbound webhook secret. The secret is
    returned ONCE and stored Fernet-encrypted alongside the credentials."""
    from app.models.domain import Connector, ConnectorCredential
    from app.services.live_connectors import decrypt_secrets, encrypt_secrets

    connector = (await db.execute(select(Connector).where(
        Connector.id == connector_id,
        Connector.tenant_id == tenant["tenant_id"],
    ))).scalar_one_or_none()
    if connector is None:
        raise HTTPException(status_code=404, detail="connector not found")

    cred = (await db.execute(select(ConnectorCredential).where(
        ConnectorCredential.connector_id == connector_id
    ))).scalar_one_or_none()
    secret = pysecrets.token_hex(32)
    if cred is None:
        cred = ConnectorCredential(
            connector_id=connector_id, tenant_id=tenant["tenant_id"],
            provider="generic_rest", config={},
            secrets_encrypted=encrypt_secrets({"webhook_secret": secret}),
        )
        db.add(cred)
    else:
        stored = {}
        try:
            stored = decrypt_secrets(cred.secrets_encrypted)
        except Exception:
            # Undecryptable prior secrets (e.g. a rotated SECRET_KEY) must not
            # block setting a new webhook secret; we start from an empty dict
            # and re-encrypt, which replaces the unreadable blob.
            pass
        stored["webhook_secret"] = secret
        cred.secrets_encrypted = encrypt_secrets(stored)
    await db.commit()
    return {
        "connector_id": connector_id,
        "webhook_secret": secret,
        "ingest_url": f"/api/v1/integrations/ingest/{connector_id}",
        "note": "Shown once. Sign requests: X-KAEOS-Signature = "
                "HMAC-SHA256(secret, raw_body) hex.",
    }


@router.get("/sync/ledger")
async def sync_ledger(
    limit: int = 50,
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    from app.models.sync import SyncLedger
    limit = max(1, min(200, limit))
    rows = (await db.execute(
        select(SyncLedger).where(SyncLedger.tenant_id == tenant_id)
        .order_by(SyncLedger.created_at.desc()).limit(limit)
    )).scalars().all()
    return {"ledger": [
        {"id": r.id, "provider": r.provider, "direction": r.direction,
         "entity_type": r.entity_type, "external_id": r.external_id,
         "internal_id": r.internal_id, "op": r.op, "status": r.status,
         "detail": r.detail, "created_at": str(r.created_at) if r.created_at else None}
        for r in rows
    ]}


@router.get("/sync/outbound")
async def outbound_queue(
    limit: int = 50,
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    from app.models.sync import OutboundWrite
    limit = max(1, min(200, limit))
    rows = (await db.execute(
        select(OutboundWrite).where(OutboundWrite.tenant_id == tenant_id)
        .order_by(OutboundWrite.created_at.desc()).limit(limit)
    )).scalars().all()
    return {"outbound": [
        {"id": r.id, "provider": r.provider, "category": r.category,
         "entity_type": r.entity_type, "internal_id": r.internal_id,
         "external_id": r.external_id, "op": r.op, "status": r.status,
         "attempts": r.attempts, "last_error": r.last_error,
         "created_at": str(r.created_at) if r.created_at else None}
        for r in rows
    ]}


@router.post("/sync/outbound/dispatch")
async def dispatch_now(
    tenant: dict = Depends(require_role("operator")),
):
    """Manually kick the outbound dispatcher (it also runs on the scheduler)."""
    from app.services.sync_engine import dispatch_outbound
    return await dispatch_outbound(tenant_id=tenant["tenant_id"])
