"""Sense-Decide-Act Event Mesh API (v3 Phase 5).

Ingest an external-world signal, correlate it to the twin, and enact a governed
response. Connectors (or an operator) POST signals; anyone with read access sees
the Signals & Responses stream.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, func, case
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.tenant import get_tenant_id, require_role
from app.core.audit import record_security_event
from app.models.event_mesh import ExternalSignal, SIGNAL_KINDS
from app.services.event_mesh import correlate, respond

router = APIRouter(prefix="/signals", tags=["Event Mesh"])


class SignalIn(BaseModel):
    kind: str
    title: str
    body: Optional[str] = None
    source: Optional[str] = None
    severity: str = "info"
    authority_score: float = 0.6
    novelty_score: float = 0.6
    auto_respond: bool = True


def _to_dict(s: ExternalSignal) -> dict:
    return {
        "id": s.id, "kind": s.kind, "title": s.title, "body": s.body, "source": s.source,
        "severity": s.severity, "authority_score": s.authority_score, "novelty_score": s.novelty_score,
        "matched_entities": s.matched_entities or [], "correlation_note": s.correlation_note,
        "response_kind": s.response_kind, "response_ref": s.response_ref, "status": s.status,
        "created_at": s.created_at.isoformat() if s.created_at else None,
        "responded_at": s.responded_at.isoformat() if s.responded_at else None,
    }


@router.post("/ingest")
async def ingest_signal(
    body: SignalIn,
    tenant: dict = Depends(require_role("operator")),
    db: AsyncSession = Depends(get_db),
):
    """Ingest an external signal: persist, correlate to the twin, and (optionally)
    enact the governed response."""
    kind = (body.kind or "").strip().upper()
    if kind not in SIGNAL_KINDS:
        raise HTTPException(status_code=400, detail=f"kind must be one of {sorted(SIGNAL_KINDS)}")
    if body.severity not in ("info", "warning", "critical"):
        raise HTTPException(status_code=400, detail="severity must be info|warning|critical")
    tenant_id = tenant["tenant_id"]

    signal = ExternalSignal(
        tenant_id=tenant_id, kind=kind, title=body.title.strip(), body=body.body,
        source=body.source, severity=body.severity,
        authority_score=body.authority_score, novelty_score=body.novelty_score, status="NEW")
    db.add(signal)
    await correlate(db, tenant_id, signal)
    if body.auto_respond:
        await respond(db, tenant_id, signal)
    await db.commit()
    await db.refresh(signal)
    await record_security_event(
        tenant_id=tenant_id, event_type="SIGNAL", action="INGEST",
        actor=tenant.get("name"), actor_role=tenant.get("role"),
        resource_type="external_signal", resource_id=signal.id,
        details={"kind": kind, "response": signal.response_kind})
    return _to_dict(signal)


@router.get("")
async def list_signals(
    limit: int = 50,
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """The Signals & Responses stream with a summary. Real records only."""
    limit = max(1, min(200, limit))
    scope = ExternalSignal.tenant_id == tenant_id
    responded = func.count(case((ExternalSignal.status == "RESPONDED", 1)))
    actioned = func.count(case((ExternalSignal.response_kind.in_(["HITL", "MISSION"]), 1)))
    row = (await db.execute(select(func.count(), responded, actioned).where(scope))).one()
    rows = (await db.execute(
        select(ExternalSignal).where(scope).order_by(ExternalSignal.created_at.desc()).limit(limit)
    )).scalars().all()
    return {
        "summary": {"total": int(row[0] or 0), "responded": int(row[1] or 0), "actioned": int(row[2] or 0)},
        "signals": [_to_dict(s) for s in rows],
        "note": "External signals correlated to the twin; an uncorrelated signal gets no action.",
    }


@router.post("/{signal_id}/respond")
async def respond_signal(
    signal_id: str,
    tenant: dict = Depends(require_role("operator")),
    db: AsyncSession = Depends(get_db),
):
    """Manually enact the governed response for a correlated signal."""
    tenant_id = tenant["tenant_id"]
    signal = (await db.execute(
        select(ExternalSignal).where(ExternalSignal.id == signal_id, ExternalSignal.tenant_id == tenant_id)
    )).scalar_one_or_none()
    if signal is None:
        raise HTTPException(status_code=404, detail="signal not found")
    await respond(db, tenant_id, signal)
    await db.commit()
    await db.refresh(signal)
    return _to_dict(signal)
