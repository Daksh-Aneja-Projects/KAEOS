from app.core.tenant import get_tenant_id
"""
KAEOS Workforce API — Processes
Business process endpoints for the workforce layer.

Each BusinessProcess belongs to a Capability within a Department.
The process_graph field contains React Flow-compatible nodes/edges.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional

from app.core.database import get_db
from app.workforce.models.core import BusinessProcess

router = APIRouter(prefix="/workforce/processes", tags=["Workforce — Processes"])


@router.get("")
async def list_processes(
    department_id: Optional[str] = None,
    capability_id: Optional[str] = None,
    status: Optional[str] = None,
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """List all business processes, optionally filtered by department or capability."""
    q = select(BusinessProcess).where(BusinessProcess.tenant_id == tenant_id)
    if department_id:
        q = q.where(BusinessProcess.department_id == department_id)
    if capability_id:
        q = q.where(BusinessProcess.capability_id == capability_id)
    if status:
        q = q.where(BusinessProcess.status == status)
    q = q.order_by(BusinessProcess.name)

    result = await db.execute(q)
    processes = result.scalars().all()

    return {
        "total": len(processes),
        "processes": [
            {
                "id": p.id,
                "name": p.name,
                "slug": p.slug,
                "description": p.description,
                "department_id": p.department_id,
                "capability_id": p.capability_id,
                "status": p.status,
                "trigger_type": p.trigger_type,
                "automation_pct": p.automation_pct,
                "execution_count": p.execution_count,
                "avg_duration_ms": p.avg_duration_ms,
                "success_rate": p.success_rate,
                "sla_hours": p.sla_hours,
                "last_executed_at": str(p.last_executed_at) if p.last_executed_at else None,
            }
            for p in processes
        ],
    }


@router.get("/{process_id}")
async def get_process(
    process_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Get a single process with full detail including process graph."""
    result = await db.execute(
        select(BusinessProcess).where(BusinessProcess.id == process_id)
    )
    p = result.scalar_one_or_none()
    if not p:
        raise HTTPException(status_code=404, detail="Process not found")

    return {
        "id": p.id,
        "name": p.name,
        "slug": p.slug,
        "description": p.description,
        "department_id": p.department_id,
        "capability_id": p.capability_id,
        "status": p.status,
        "trigger_type": p.trigger_type,
        "trigger_config": p.trigger_config or {},
        "automation_pct": p.automation_pct,
        "execution_count": p.execution_count,
        "avg_duration_ms": p.avg_duration_ms,
        "success_rate": p.success_rate,
        "sla_hours": p.sla_hours,
        "escalation_after_hours": p.escalation_after_hours,
        "process_graph": p.process_graph or {},
        "steps": p.steps or [],
        "version": p.version,
        "last_executed_at": str(p.last_executed_at) if p.last_executed_at else None,
        "created_at": str(p.created_at) if p.created_at else None,
        "updated_at": str(p.updated_at) if p.updated_at else None,
    }
