"""Bidirectional sync API - realtime inbound ingest + outbound write-back ops.

The ingest endpoint is PUBLIC (external systems cannot hold KAEOS JWTs); each
request is authenticated by an HMAC-SHA256 signature over the raw body using
the connector's webhook_secret. Everything else is operator/admin-gated.
"""
import secrets as pysecrets
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import record_security_event
from app.core.database import get_db
from app.core.tenant import get_tenant_id, require_role
from app.core.tenant import approver_identity

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
    # Rotating the PUBLIC ingest webhook secret is a credential config change;
    # audit it the same way connectors.py audits every credential mutation.
    await record_security_event(
        tenant_id=tenant["tenant_id"], event_type="CONFIG_CHANGE", action="WRITE",
        actor=approver_identity(tenant), actor_role=tenant.get("role"),
        resource_type="connector_credentials", resource_id=connector_id,
    )
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


# The full outbound status set (see models/sync.py OutboundWrite.status).
_OUTBOUND_STATUSES = ("PENDING", "SENT", "FAILED", "DEAD",
                      "SKIPPED_NO_CONNECTOR", "SKIPPED_NO_CREDENTIALS")

# States an operator can replay back to PENDING. DEAD/FAILED = retries exhausted
# or transient error; the SKIPPED_* states = a write queued before its connector
# existed, otherwise a permanent dead-end (dispatch reselects only PENDING/FAILED).
_REQUEUABLE_STATUSES = ("DEAD", "FAILED", "SKIPPED_NO_CONNECTOR", "SKIPPED_NO_CREDENTIALS")


@router.get("/sync/outbound")
async def outbound_queue(
    limit: int = 50,
    status: Optional[str] = Query(None, pattern=f"^({'|'.join(_OUTBOUND_STATUSES)})$"),
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    from app.models.sync import OutboundWrite
    limit = max(1, min(200, limit))
    q = select(OutboundWrite).where(OutboundWrite.tenant_id == tenant_id)
    if status:
        q = q.where(OutboundWrite.status == status)
    rows = (await db.execute(
        q.order_by(OutboundWrite.created_at.desc()).limit(limit)
    )).scalars().all()
    counts = {s: n for s, n in (await db.execute(
        select(OutboundWrite.status, func.count()).where(
            OutboundWrite.tenant_id == tenant_id
        ).group_by(OutboundWrite.status)
    )).all()}
    return {"outbound": [
        {"id": r.id, "provider": r.provider, "category": r.category,
         "entity_type": r.entity_type, "internal_id": r.internal_id,
         "external_id": r.external_id, "op": r.op, "status": r.status,
         "attempts": r.attempts, "last_error": r.last_error,
         "created_at": str(r.created_at) if r.created_at else None}
        for r in rows
    ], "counts": counts}


@router.post("/sync/outbound/dispatch")
async def dispatch_now(
    tenant: dict = Depends(require_role("operator")),
):
    """Manually kick the outbound dispatcher (it also runs on the scheduler)."""
    from app.services.sync_engine import dispatch_outbound
    result = await dispatch_outbound(tenant_id=tenant["tenant_id"])
    await record_security_event(
        tenant_id=tenant["tenant_id"], event_type="MODIFICATION", action="EXECUTE",
        actor=approver_identity(tenant), actor_role=tenant.get("role"),
        resource_type="outbound_write",
    )
    return result


@router.post("/sync/outbound/{write_id}/requeue")
async def requeue_outbound(
    write_id: str,
    tenant: dict = Depends(require_role("operator")),
    db: AsyncSession = Depends(get_db),
):
    """Operator replay of a write that stalled: back to PENDING with a fresh
    retry budget. The idempotency_key is deliberately KEPT so the system of
    record dedups the replay instead of creating a duplicate record.

    Accepts DEAD/FAILED (retries exhausted or transient error) AND the terminal
    SKIPPED_NO_CONNECTOR / SKIPPED_NO_CREDENTIALS states: a governed write queued
    before its connector was connected would otherwise be an unrecoverable
    dead-end (skips are excluded from dispatch reselection). Once the connector
    is connected, requeue is its recovery path."""
    from app.models.sync import OutboundWrite
    w = (await db.execute(select(OutboundWrite).where(
        OutboundWrite.id == write_id,
        OutboundWrite.tenant_id == tenant["tenant_id"],
    ))).scalar_one_or_none()
    if w is None:
        raise HTTPException(status_code=404, detail="outbound write not found")
    if w.status not in _REQUEUABLE_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"only DEAD, FAILED, or SKIPPED writes can be requeued (status is {w.status})")
    w.status = "PENDING"
    w.attempts = 0
    w.last_error = None
    await db.commit()
    await record_security_event(
        tenant_id=tenant["tenant_id"], event_type="MODIFICATION", action="WRITE",
        actor=approver_identity(tenant), actor_role=tenant.get("role"),
        resource_type="outbound_write", resource_id=w.id,
    )
    return {"id": w.id, "status": w.status, "attempts": w.attempts,
            "idempotency_key": w.idempotency_key}
