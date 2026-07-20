"""KAEOS — Conflict Arena API (L16 Conflict Resolution)"""
from app.core.tenant import get_tenant_id, require_role
from app.core.audit import record_security_event
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime, timezone
from pydantic import BaseModel
from typing import Optional

from app.core.database import get_db
from app.models.domain import ConflictCase, Rule

router = APIRouter(prefix="/conflicts", tags=["Conflicts — L16 Arena"])


class ResolveRequest(BaseModel):
    resolution_type: str
    resolution_note: Optional[str] = None


@router.get("")
async def list_conflicts(
    status: str | None = None,
    tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db),
):
    """List all conflict cases from the DB. Tenant-scoped to the caller."""
    q = select(ConflictCase).where(ConflictCase.tenant_id == tenant_id)
    if status:
        q = q.where(ConflictCase.status == status)
    q = q.order_by(ConflictCase.detected_at.desc()).limit(200)

    result = await db.execute(q)
    cases = result.scalars().all()

    # Fetch every referenced rule in ONE query (was an N+1: two SELECTs per case).
    rule_ids = {c.rule_a_id for c in cases} | {c.rule_b_id for c in cases}
    rule_ids.discard(None)
    rules_by_id = {}
    if rule_ids:
        rules_res = await db.execute(
            select(Rule).where(Rule.tenant_id == tenant_id, Rule.id.in_(rule_ids))
        )
        rules_by_id = {r.id: r for r in rules_res.scalars().all()}

    items = []
    for c in cases:
        ra = rules_by_id.get(c.rule_a_id)
        rb = rules_by_id.get(c.rule_b_id)
        items.append({
            "id": c.id,
            "conflict_type": c.conflict_type,
            "severity": c.severity,
            "status": c.status,
            "assigned_to": c.assigned_to,
            "deadline": c.deadline.isoformat() if c.deadline else None,
            "detected_at": c.detected_at.isoformat() if c.detected_at else None,
            "resolved_at": c.resolved_at.isoformat() if c.resolved_at else None,
            "resolution_type": c.resolution_type,
            "resolution_note": c.resolution_note,
            "rule_a": {
                "id": ra.id, "statement": ra.statement, "domain": ra.domain,
                "confidence": ra.confidence_scalar,
                "sources": len(ra.source_signals) if ra.source_signals else 0,
                "validated_at": ra.validated_at.isoformat() if ra.validated_at else None,
            } if ra else None,
            "rule_b": {
                "id": rb.id, "statement": rb.statement, "domain": rb.domain,
                "confidence": rb.confidence_scalar,
                "sources": len(rb.source_signals) if rb.source_signals else 0,
                "validated_at": rb.validated_at.isoformat() if rb.validated_at else None,
            } if rb else None,
        })

    open_count = sum(1 for c in cases if c.status in ("OPEN", "IN_REVIEW"))
    return {"conflicts": items, "open_count": open_count, "total": len(items)}


@router.post("/{conflict_id}/resolve")
async def resolve_conflict(
    conflict_id: str,
    body: ResolveRequest,
    tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db),
):
    """Resolve a conflict case. Tenant-scoped to the caller."""
    tenant_id = tenant["tenant_id"]
    result = await db.execute(
        select(ConflictCase)
        .where(ConflictCase.tenant_id == tenant_id)
        .where(ConflictCase.id == conflict_id)
    )
    case = result.scalar_one_or_none()
    if not case:
        raise HTTPException(404, "Conflict not found")

    case.status = "RESOLVED"
    case.resolution_type = body.resolution_type
    case.resolution_note = body.resolution_note
    case.resolved_at = datetime.now(timezone.utc)
    await db.commit()
    await record_security_event(
        tenant_id=tenant_id, event_type="MODIFICATION", action="WRITE",
        actor=tenant.get("name"), actor_role=tenant.get("role"),
        resource_type="conflict_case", resource_id=conflict_id,
    )
    return {"status": "RESOLVED", "conflict_id": conflict_id}
