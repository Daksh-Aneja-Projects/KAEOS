"""KAEOS — Enterprise Connectors API (L0 Data Fabric Connector Mesh)"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func as sqlfunc
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from app.core.database import get_db
from app.models.domain import Connector, ConnectorCredential

router = APIRouter(prefix="/connectors", tags=["Connectors — L0 Data Fabric"])
from app.core.tenant import get_tenant_id, require_role


class CredentialsBody(BaseModel):
    provider: Optional[str] = None          # inferred from connector when omitted
    config: Dict[str, Any] = {}             # non-secret settings (base_url, filters…)
    secrets: Dict[str, Any] = {}            # tokens/passwords — encrypted at rest


@router.get("/providers")
async def list_supported_providers():
    """
    Catalog of every live integration KAEOS can talk to.

    Declared before /{connector_id} routes so "providers" is never swallowed as
    a connector id. Returns no secrets — this is a public capability listing.
    """
    from app.services.live_connectors import list_providers

    providers = list_providers()
    by_domain: Dict[str, list] = {}
    for p in providers:
        by_domain.setdefault(p["domain"], []).append(p["id"])
    return {"total": len(providers), "providers": providers, "by_domain": by_domain}


async def _get_connector(connector_id: str, tenant_id: str, db: AsyncSession) -> Connector:
    result = await db.execute(
        select(Connector).where(Connector.id == connector_id, Connector.tenant_id == tenant_id))
    conn = result.scalar_one_or_none()
    if not conn:
        raise HTTPException(404, "Connector not found")
    return conn

@router.get("")
async def list_connectors(
    category: str | None = None,
    status: str | None = None,
    db: AsyncSession = Depends(get_db),
    tenant_id: str = Depends(get_tenant_id)
):
    """List all enterprise integration connectors with optional filtering."""
    q = select(Connector).where(Connector.tenant_id == tenant_id)
    if category:
        q = q.where(Connector.category == category)
    if status:
        q = q.where(Connector.status == status)
    q = q.order_by(Connector.events_ingested.desc())

    result = await db.execute(q)
    connectors = result.scalars().all()

    cred_rows = (await db.execute(
        select(ConnectorCredential.connector_id, ConnectorCredential.provider,
               ConnectorCredential.last_test_ok)
        .where(ConnectorCredential.tenant_id == tenant_id)
    )).all()
    creds_by_id = {r[0]: {"provider": r[1], "last_test_ok": r[2]} for r in cred_rows}

    total_events = sum(c.events_ingested for c in connectors)
    total_signals = sum(c.signals_extracted for c in connectors)
    connected_count = sum(1 for c in connectors if c.status == "CONNECTED")

    return {
        "connectors": [
            {
                "id": c.id,
                "name": c.name,
                "category": c.category,
                "connector_type": c.connector_type,
                "status": c.status,
                "icon": c.icon,
                "description": c.description,
                "auth_method": c.auth_method,
                "sync_frequency": c.sync_frequency,
                "last_sync_at": c.last_sync_at.isoformat() if c.last_sync_at else None,
                "events_ingested": c.events_ingested,
                "signals_extracted": c.signals_extracted,
                "error_count": c.error_count,
                "avg_latency_ms": c.avg_latency_ms,
                "pii_scrub_enabled": c.pii_scrub_enabled,
                "pii_entities_found": c.pii_entities_found,
                "connected_at": c.connected_at.isoformat() if c.connected_at else None,
                "live_integration": creds_by_id.get(c.id),  # provider + last_test_ok, None if demo feed
            }
            for c in connectors
        ],
        "stats": {
            "total": len(connectors),
            "connected": connected_count,
            "available": len(connectors) - connected_count,
            "total_events_ingested": total_events,
            "total_signals_extracted": total_signals,
        },
    }


@router.put("/{connector_id}/credentials")
async def store_credentials(
    connector_id: str,
    body: CredentialsBody,
    db: AsyncSession = Depends(get_db),
    tenant: dict = Depends(require_role("admin")),
):
    """Store live-integration credentials for a connector (secrets encrypted at rest).

    After this, /test verifies the connection and /sync pulls real records.
    """
    from app.services.live_connectors import (
        LiveConnectorService, infer_provider, encrypt_secrets,
    )
    conn = await _get_connector(connector_id, tenant["tenant_id"], db)

    provider = (body.provider or infer_provider(conn.name, conn.category)).lower()
    error = LiveConnectorService.validate(provider, body.config)
    if error:
        raise HTTPException(400, error)

    cred = (await db.execute(
        select(ConnectorCredential).where(ConnectorCredential.connector_id == conn.id)
    )).scalar_one_or_none()
    if cred:
        cred.provider = provider
        cred.config = body.config
        cred.secrets_encrypted = encrypt_secrets(body.secrets)
        cred.last_test_ok = None
        cred.last_test_detail = None
    else:
        db.add(ConnectorCredential(
            connector_id=conn.id, tenant_id=tenant["tenant_id"],
            provider=provider, config=body.config,
            secrets_encrypted=encrypt_secrets(body.secrets),
        ))
    await db.commit()
    return {
        "status": "CREDENTIALS_STORED", "connector": conn.name, "provider": provider,
        "secret_keys_stored": sorted(body.secrets.keys()),
        "next": f"POST /connectors/{conn.id}/test to verify, then /connect and /sync",
    }


@router.get("/{connector_id}/credentials")
async def credential_status(
    connector_id: str,
    db: AsyncSession = Depends(get_db),
    tenant_id: str = Depends(get_tenant_id),
):
    """Masked credential status — secret VALUES are never returned, only key names."""
    from app.services.live_connectors import decrypt_secrets, infer_provider, REQUIRED_CONFIG
    conn = await _get_connector(connector_id, tenant_id, db)
    cred = (await db.execute(
        select(ConnectorCredential).where(ConnectorCredential.connector_id == conn.id)
    )).scalar_one_or_none()

    inferred = infer_provider(conn.name, conn.category)
    if not cred:
        return {
            "configured": False,
            "inferred_provider": inferred,
            "required_config": REQUIRED_CONFIG.get(inferred, []),
        }

    try:
        secret_keys = sorted(decrypt_secrets(cred.secrets_encrypted).keys())
    except ValueError:
        secret_keys = ["<undecryptable — re-enter credentials>"]

    return {
        "configured": True,
        "provider": cred.provider,
        "config": cred.config or {},           # non-secret settings only
        "secret_keys": secret_keys,             # names only, never values
        "last_test_ok": cred.last_test_ok,
        "last_test_detail": cred.last_test_detail,
        "last_tested_at": cred.last_tested_at.isoformat() if cred.last_tested_at else None,
    }


@router.delete("/{connector_id}/credentials")
async def delete_credentials(
    connector_id: str,
    db: AsyncSession = Depends(get_db),
    tenant: dict = Depends(require_role("admin")),
):
    """Remove stored credentials — connector falls back to the simulated demo feed."""
    conn = await _get_connector(connector_id, tenant["tenant_id"], db)
    cred = (await db.execute(
        select(ConnectorCredential).where(ConnectorCredential.connector_id == conn.id)
    )).scalar_one_or_none()
    if not cred:
        raise HTTPException(404, "No credentials stored for this connector")
    await db.delete(cred)
    await db.commit()
    return {"status": "CREDENTIALS_DELETED", "connector": conn.name}


@router.post("/{connector_id}/test")
async def test_connection(
    connector_id: str,
    db: AsyncSession = Depends(get_db),
    tenant_id: str = Depends(get_tenant_id),
):
    """Attempt a live connection with the stored credentials."""
    from app.services.live_connectors import LiveConnectorService, decrypt_secrets
    conn = await _get_connector(connector_id, tenant_id, db)
    cred = (await db.execute(
        select(ConnectorCredential).where(ConnectorCredential.connector_id == conn.id)
    )).scalar_one_or_none()
    if not cred:
        raise HTTPException(400, "No credentials stored — PUT /credentials first")

    try:
        secrets = decrypt_secrets(cred.secrets_encrypted)
    except ValueError as e:
        raise HTTPException(500, str(e))

    result = await LiveConnectorService.test_connection(cred.provider, cred.config or {}, secrets)
    cred.last_test_ok = result["ok"]
    cred.last_test_detail = result["detail"][:500]
    cred.last_tested_at = datetime.now(timezone.utc)
    await db.commit()
    return {"connector": conn.name, "provider": cred.provider, **result}


@router.post("/{connector_id}/connect")
async def connect_connector(
    connector_id: str,
    body: Optional[CredentialsBody] = None,
    db: AsyncSession = Depends(get_db),
    tenant: dict = Depends(require_role("admin")),
):
    """Connect/activate an enterprise integration.

    Optionally pass credentials inline (same shape as PUT /credentials) to
    store-and-connect in one call.
    """
    conn = await _get_connector(connector_id, tenant["tenant_id"], db)

    if body and (body.config or body.secrets):
        from app.services.live_connectors import (
            LiveConnectorService, infer_provider, encrypt_secrets,
        )
        provider = (body.provider or infer_provider(conn.name, conn.category)).lower()
        error = LiveConnectorService.validate(provider, body.config)
        if error:
            raise HTTPException(400, error)
        cred = (await db.execute(
            select(ConnectorCredential).where(ConnectorCredential.connector_id == conn.id)
        )).scalar_one_or_none()
        if cred:
            cred.provider = provider
            cred.config = body.config
            cred.secrets_encrypted = encrypt_secrets(body.secrets)
        else:
            db.add(ConnectorCredential(
                connector_id=conn.id, tenant_id=tenant["tenant_id"],
                provider=provider, config=body.config,
                secrets_encrypted=encrypt_secrets(body.secrets),
            ))

    conn.status = "CONNECTED"
    conn.connected_at = datetime.now(timezone.utc)
    conn.last_sync_at = datetime.now(timezone.utc)
    await db.commit()
    return {"status": "CONNECTED", "connector": conn.name}


@router.post("/{connector_id}/disconnect")
async def disconnect_connector(connector_id: str, db: AsyncSession = Depends(get_db), tenant: dict = Depends(require_role("admin"))):
    """Pause/disconnect an enterprise integration."""
    result = await db.execute(select(Connector).where(Connector.id == connector_id, Connector.tenant_id == tenant["tenant_id"]))
    conn = result.scalar_one_or_none()
    if not conn:
        raise HTTPException(404, "Connector not found")

    conn.status = "PAUSED"
    await db.commit()
    return {"status": "PAUSED", "connector": conn.name}


@router.get("/{connector_id}/health")
async def connector_health(connector_id: str, db: AsyncSession = Depends(get_db), tenant_id: str = Depends(get_tenant_id)):
    """Computed health metrics for a connector — replaces frontend Math.random()."""
    result = await db.execute(select(Connector).where(Connector.id == connector_id, Connector.tenant_id == tenant_id))
    conn = result.scalar_one_or_none()
    if not conn:
        raise HTTPException(404, "Connector not found")

    # Records per hour
    records_per_hour = 0
    if conn.connected_at and conn.events_ingested:
        conn_at = conn.connected_at.replace(tzinfo=timezone.utc) if conn.connected_at.tzinfo is None else conn.connected_at
        hours_connected = max(
            (datetime.now(timezone.utc) - conn_at).total_seconds() / 3600,
            0.01,  # avoid division by zero
        )
        records_per_hour = round(conn.events_ingested / hours_connected, 1)

    # Error rate
    error_rate_pct = round(
        (conn.error_count / max(conn.events_ingested, 1)) * 100, 2
    )

    # Freshness: percentage based on how recently the last sync happened
    freshness_pct = 0.0
    freq_hours = {
        "REAL_TIME": 0.083,   # 5 minutes
        "HOURLY": 1,
        "DAILY": 24,
        "WEEKLY": 168,
    }
    expected_interval_hours = freq_hours.get(conn.sync_frequency or "DAILY", 24)
    if conn.last_sync_at:
        last_sync = conn.last_sync_at.replace(tzinfo=timezone.utc) if conn.last_sync_at.tzinfo is None else conn.last_sync_at
        hours_since_sync = (datetime.now(timezone.utc) - last_sync).total_seconds() / 3600
        freshness_pct = max(0, min(100, round(
            (1 - hours_since_sync / (expected_interval_hours * 2)) * 100, 1
        )))
    elif conn.status == "CONNECTED":
        freshness_pct = 50.0  # Connected but never synced

    from app.models.domain import Signal
    entity_q = await db.execute(
        select(Signal.source_type, sqlfunc.count(Signal.id), sqlfunc.max(Signal.created_at))
        .where(Signal.tenant_id == conn.tenant_id)
        .group_by(Signal.source_type)
    )
    entity_rows = entity_q.all()

    entity_freshness = []
    for source_type, count, latest in entity_rows:
        if latest:
            latest_aware = latest.replace(tzinfo=timezone.utc) if latest.tzinfo is None else latest
            hours_ago = (datetime.now(timezone.utc) - latest_aware).total_seconds() / 3600
            ent_freshness = max(0, min(100, round(
                (1 - hours_ago / (expected_interval_hours * 2)) * 100, 1
            )))
        else:
            ent_freshness = 0
        entity_freshness.append({
            "entity_type": source_type or "Unknown",
            "record_count": count,
            "freshness_pct": ent_freshness,
        })

    return {
        "connector_id": conn.id,
        "connector_name": conn.name,
        "status": conn.status,
        "records_per_hour": records_per_hour,
        "error_rate_pct": error_rate_pct,
        "freshness_pct": freshness_pct,
        "events_ingested": conn.events_ingested,
        "error_count": conn.error_count,
        "last_sync_at": conn.last_sync_at.isoformat() if conn.last_sync_at else None,
        "entity_freshness": entity_freshness,
    }


@router.get("/{connector_id}/feed")
async def connector_feed(
    connector_id: str,
    limit: int = 20,
    db: AsyncSession = Depends(get_db),
    tenant_id: str = Depends(get_tenant_id)
):
    """Recent ingestion events for a connector — replaces Array.from fake feed."""
    result = await db.execute(select(Connector).where(Connector.id == connector_id, Connector.tenant_id == tenant_id))
    conn = result.scalar_one_or_none()
    if not conn:
        raise HTTPException(404, "Connector not found")

    from app.models.domain import Signal
    sig_q = await db.execute(
        select(Signal)
        .where(Signal.tenant_id == conn.tenant_id)
        .order_by(Signal.created_at.desc())
        .limit(limit)
    )
    signals = sig_q.scalars().all()

    return {
        "connector_id": conn.id,
        "connector_name": conn.name,
        "total": len(signals),
        "events": [
            {
                "id": s.id,
                "signal_type": s.signal_type,
                "source_type": s.source_type,
                "source_entity": s.source_entity,
                "domain": s.domain,
                "authority_score": s.authority_score,
                "pii_present": s.pii_present,
                "created_at": s.created_at.isoformat() if s.created_at else None,
                "summary": (s.clean_payload[:120] + "…") if s.clean_payload and len(s.clean_payload) > 120 else s.clean_payload,
            }
            for s in signals
        ],
    }

@router.post("/{connector_id}/sync")
async def sync_connector(
    connector_id: str,
    db: AsyncSession = Depends(get_db),
    tenant_id: str = Depends(get_tenant_id)
):
    """Triggers an immediate sync for a connector."""
    result = await db.execute(select(Connector).where(Connector.id == connector_id, Connector.tenant_id == tenant_id))
    conn = result.scalar_one_or_none()
    if not conn:
        raise HTTPException(404, "Connector not found")
        
    if conn.status != "CONNECTED":
        raise HTTPException(400, "Connector is not connected")

    # ── Live path: stored credentials → pull real records from the source ──
    cred = (await db.execute(
        select(ConnectorCredential).where(ConnectorCredential.connector_id == conn.id)
    )).scalar_one_or_none()
    if cred:
        from app.services.live_connectors import LiveConnectorService, decrypt_secrets
        try:
            secrets = decrypt_secrets(cred.secrets_encrypted)
            records = await LiveConnectorService.fetch_records(
                cred.provider, cred.config or {}, secrets)
        except Exception as e:
            conn.error_count += 1
            await db.commit()
            raise HTTPException(502, f"Live sync failed ({cred.provider}): {str(e)[:200]}")

        signals = LiveConnectorService.records_to_signals(records, conn.tenant_id, conn.name)
        for s in signals:
            db.add(s)
        conn.events_ingested += len(records)
        conn.signals_extracted += len(signals)
        conn.last_sync_at = datetime.now(timezone.utc)
        await db.commit()
        return {
            "status": "success",
            "mode": "LIVE",
            "provider": cred.provider,
            "connector": conn.name,
            "events_synced": len(records),
            "signals_created": len(signals),
            "last_sync": conn.last_sync_at.isoformat(),
        }

    # ── Demo path: no credentials — deterministic simulated feed ──
    import uuid
    from app.models.domain import Signal

    # Deterministic event count: based on existing ingestion velocity, defaulting to 10
    events_found = max(5, min(20, (conn.events_ingested // 100) + 10)) if conn.events_ingested else 10
    
    # If it's BambooHR, create a real Signal record
    if "bamboo" in conn.name.lower() or conn.category == "hris":
        new_signal = Signal(
            id=f"sig_{uuid.uuid4().hex[:8]}",
            tenant_id=conn.tenant_id,
            signal_type="WEBHOOK",
            source_type="bamboohr",
            source_entity="employee_update",
            clean_payload="BambooHR sync: employee records updated",
            pii_present=True,
            authority_score=0.95,
            domain="HR",
            created_at=datetime.now(timezone.utc)
        )
        db.add(new_signal)
        conn.signals_extracted += 1
    
    # If it's Slack, create a real Signal record for the ingested message
    elif "slack" in conn.name.lower() or conn.category == "communications":
        new_signal = Signal(
            id=f"sig_{uuid.uuid4().hex[:8]}",
            tenant_id=conn.tenant_id,
            signal_type="WEBHOOK",
            source_type="slack",
            source_entity="channel_message",
            clean_payload="Slack sync: new channel messages ingested and processed",
            pii_present=False,
            authority_score=0.8,
            domain="Support",
            created_at=datetime.now(timezone.utc)
        )
        db.add(new_signal)
        conn.signals_extracted += 1

    conn.events_ingested += events_found
    conn.last_sync_at = datetime.now(timezone.utc)
    
    await db.commit()
    
    return {
        "status": "success",
        "mode": "SIMULATED",
        "connector": conn.name,
        "events_synced": events_found,
        "last_sync": conn.last_sync_at.isoformat()
    }
