"""KAEOS — Security Fabric API (L17 Zero-Trust)"""
from app.core.tenant import get_tenant_id
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func as sqlfunc

from app.core.database import get_db
from app.models.domain import SecurityAuditLog

router = APIRouter(prefix="/security", tags=["Security — L17 Zero-Trust Fabric"])


@router.get("/audit-log")
async def get_audit_log(
    event_type: str | None = None,
    result_filter: str | None = None,
    limit: int = 50,
    tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db),
):
    """Get security audit log entries from DB. Tenant-scoped to the caller."""
    q = select(SecurityAuditLog).where(SecurityAuditLog.tenant_id == tenant_id)
    if event_type:
        q = q.where(SecurityAuditLog.event_type == event_type)
    if result_filter:
        q = q.where(SecurityAuditLog.result == result_filter)
    q = q.order_by(SecurityAuditLog.timestamp.desc()).limit(limit)

    result = await db.execute(q)
    logs = result.scalars().all()

    # Compute stats
    total_q = await db.execute(
        select(sqlfunc.count(SecurityAuditLog.id))
        .where(SecurityAuditLog.tenant_id == tenant_id)
    )
    blocked_q = await db.execute(
        select(sqlfunc.count(SecurityAuditLog.id))
        .where(SecurityAuditLog.tenant_id == tenant_id)
        .where(SecurityAuditLog.result == "BLOCKED")
    )
    escalated_q = await db.execute(
        select(sqlfunc.count(SecurityAuditLog.id))
        .where(SecurityAuditLog.tenant_id == tenant_id)
        .where(SecurityAuditLog.result == "ESCALATED")
    )

    total_events = total_q.scalar() or 0
    blocked_events = blocked_q.scalar() or 0
    escalated_events = escalated_q.scalar() or 0

    return {
        "logs": [
            {
                "id": l.id, "event_type": l.event_type,
                "actor_hash": l.actor_hash, "actor_role": l.actor_role,
                "resource_type": l.resource_type, "resource_id": l.resource_id,
                "action": l.action, "result": l.result,
                "ip_address": l.ip_address, "details": l.details,
                "timestamp": l.timestamp.isoformat() if l.timestamp else None,
            }
            for l in logs
        ],
        "stats": {
            "total_events": total_events,
            "blocked": blocked_events,
            "escalated": escalated_events,
            "allowed": total_events - blocked_events - escalated_events,
        },
    }
