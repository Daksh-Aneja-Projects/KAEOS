"""Notification channels API - configure where KAEOS reaches humans.

Admin-gated CRUD over tenant notification channels (SMTP / Slack / webhook),
a real test-send, and the delivery ledger. Channel secrets are Fernet-encrypted
at rest and always masked on read.
"""
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.tenant import get_tenant_id, require_role
from app.models.notifications import (
    CHANNEL_KINDS, NOTIFY_EVENTS, NotificationChannel, NotificationDelivery,
)
from app.services.live_connectors import decrypt_secrets, encrypt_secrets
from app.services.notifier import _deliver_one

router = APIRouter(prefix="/notifications", tags=["Notifications"])

_SECRET_KEYS = {"password", "webhook_url", "secret", "url"}


def _mask_config(cfg: Dict[str, Any]) -> Dict[str, Any]:
    masked = {}
    for k, v in cfg.items():
        if k in _SECRET_KEYS and v:
            s = str(v)
            masked[k] = (s[:8] + "..." ) if len(s) > 12 else "***"
        else:
            masked[k] = v
    return masked


def _serialize(ch: NotificationChannel) -> Dict[str, Any]:
    try:
        cfg = _mask_config(decrypt_secrets(ch.config_encrypted))
    except Exception:
        cfg = {"error": "config unreadable"}
    return {
        "id": ch.id, "name": ch.name, "kind": ch.kind, "config": cfg,
        "events": ch.events or [], "enabled": ch.enabled,
        "created_at": str(ch.created_at) if ch.created_at else None,
    }


class ChannelIn(BaseModel):
    name: str
    kind: str
    config: Dict[str, Any]
    events: List[str] = []
    enabled: bool = True


class ChannelPatch(BaseModel):
    name: Optional[str] = None
    config: Optional[Dict[str, Any]] = None
    events: Optional[List[str]] = None
    enabled: Optional[bool] = None


def _validate(kind: str, config: Dict[str, Any], events: List[str]) -> None:
    if kind not in CHANNEL_KINDS:
        raise HTTPException(400, f"kind must be one of {CHANNEL_KINDS}")
    bad = [e for e in events if e not in NOTIFY_EVENTS]
    if bad:
        raise HTTPException(400, f"unknown events {bad}; known: {list(NOTIFY_EVENTS)}")
    required = {"smtp": ["host"], "slack": ["webhook_url"], "webhook": ["url"]}[kind]
    missing = [k for k in required if not config.get(k)]
    if missing:
        raise HTTPException(400, f"{kind} channel config missing {missing}")


@router.get("/events")
async def list_events():
    """The event vocabulary channels can subscribe to."""
    return {"events": list(NOTIFY_EVENTS), "kinds": list(CHANNEL_KINDS)}


@router.get("/channels")
async def list_channels(
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    rows = (await db.execute(
        select(NotificationChannel)
        .where(NotificationChannel.tenant_id == tenant_id)
        .order_by(NotificationChannel.created_at)
    )).scalars().all()
    return {"channels": [_serialize(c) for c in rows]}


@router.post("/channels", status_code=201)
async def create_channel(
    body: ChannelIn,
    tenant: dict = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    _validate(body.kind, body.config, body.events)
    ch = NotificationChannel(
        tenant_id=tenant["tenant_id"], name=body.name.strip()[:128],
        kind=body.kind, config_encrypted=encrypt_secrets(body.config),
        events=body.events, enabled=body.enabled,
    )
    db.add(ch)
    await db.commit()
    await db.refresh(ch)
    return _serialize(ch)


@router.patch("/channels/{channel_id}")
async def update_channel(
    channel_id: str,
    body: ChannelPatch,
    tenant: dict = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    ch = (await db.execute(
        select(NotificationChannel).where(
            NotificationChannel.id == channel_id,
            NotificationChannel.tenant_id == tenant["tenant_id"],
        )
    )).scalar_one_or_none()
    if ch is None:
        raise HTTPException(404, "channel not found")
    if body.config is not None:
        # Merge: keep stored secrets the caller did not resend (masked values).
        stored = decrypt_secrets(ch.config_encrypted)
        merged = {**stored, **{k: v for k, v in body.config.items()
                               if not (isinstance(v, str) and v.endswith("..."))}}
        _validate(ch.kind, merged, body.events if body.events is not None else (ch.events or []))
        ch.config_encrypted = encrypt_secrets(merged)
    if body.name is not None:
        ch.name = body.name.strip()[:128]
    if body.events is not None:
        bad = [e for e in body.events if e not in NOTIFY_EVENTS]
        if bad:
            raise HTTPException(400, f"unknown events {bad}")
        ch.events = body.events
    if body.enabled is not None:
        ch.enabled = body.enabled
    db.add(ch)
    await db.commit()
    await db.refresh(ch)
    return _serialize(ch)


@router.delete("/channels/{channel_id}", status_code=204)
async def delete_channel(
    channel_id: str,
    tenant: dict = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    ch = (await db.execute(
        select(NotificationChannel).where(
            NotificationChannel.id == channel_id,
            NotificationChannel.tenant_id == tenant["tenant_id"],
        )
    )).scalar_one_or_none()
    if ch is None:
        raise HTTPException(404, "channel not found")
    await db.delete(ch)
    await db.commit()


@router.post("/channels/{channel_id}/test")
async def test_channel(
    channel_id: str,
    tenant: dict = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """Send a REAL test message through the channel and report the outcome."""
    ch = (await db.execute(
        select(NotificationChannel).where(
            NotificationChannel.id == channel_id,
            NotificationChannel.tenant_id == tenant["tenant_id"],
        )
    )).scalar_one_or_none()
    if ch is None:
        raise HTTPException(404, "channel not found")
    error = await _deliver_one(
        ch, "test", "KAEOS test notification",
        "This is a test message from KAEOS. Your channel is configured correctly.",
        {"test": True}, None,
    )
    db.add(NotificationDelivery(
        tenant_id=tenant["tenant_id"], channel_id=ch.id, event="test",
        subject="KAEOS test notification",
        status="SENT" if error is None else "FAILED", error=error,
    ))
    await db.commit()
    return {"ok": error is None, "error": error}


@router.get("/deliveries")
async def list_deliveries(
    limit: int = 50,
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    limit = max(1, min(200, limit))
    rows = (await db.execute(
        select(NotificationDelivery)
        .where(NotificationDelivery.tenant_id == tenant_id)
        .order_by(NotificationDelivery.created_at.desc())
        .limit(limit)
    )).scalars().all()
    return {"deliveries": [
        {"id": d.id, "channel_id": d.channel_id, "event": d.event,
         "subject": d.subject, "status": d.status, "error": d.error,
         "created_at": str(d.created_at) if d.created_at else None}
        for d in rows
    ]}
