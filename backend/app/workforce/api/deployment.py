"""
KAEOS Workforce API — Deployment
Deploy state machine endpoints — the critical path for Department-as-a-Service.

User flow: Select Pack → Connect Systems → Review → Deploy
Each step advances the WorkforceDeployment state machine.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from typing import List, Optional

from app.core.database import get_db
from app.core.tenant import get_tenant_id
from app.workforce.models.core import WorkforceDeployment, DeploymentStatus

router = APIRouter(prefix="/workforce/deployments", tags=["Workforce — Deployment"])


class DeploymentCreateRequest(BaseModel):
    domain_pack_id: str
    domain_pack_slug: Optional[str] = None
    selected_capabilities: List[str] = []
    connected_systems: List[str] = []
    employee_count: int = 0


class DeploymentAdvanceRequest(BaseModel):
    step_data: dict = {}


@router.get("/")
async def list_deployments(
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """List all deployment records for a tenant."""
    result = await db.execute(
        select(WorkforceDeployment)
        .where(WorkforceDeployment.tenant_id == tenant_id)
        .order_by(WorkforceDeployment.started_at.desc())
    )
    deployments = result.scalars().all()

    return {
        "total": len(deployments),
        "deployments": [
            {
                "id": d.id,
                "department_id": d.department_id,
                "domain_pack_id": d.domain_pack_id,
                "domain_pack_slug": d.domain_pack_slug,
                "status": d.status.value if isinstance(d.status, DeploymentStatus) else d.status,
                "current_step": d.current_step,
                "progress_pct": d.progress_pct,
                "selected_capabilities": d.selected_capabilities or [],
                "connected_systems": d.connected_systems or [],
                "employee_count": d.employee_count,
                "agents_created": d.agents_created or [],
                "error_log": d.error_log or [],
                "started_at": str(d.started_at) if d.started_at else None,
                "completed_at": str(d.completed_at) if d.completed_at else None,
            }
            for d in deployments
        ],
    }


@router.get("/{deployment_id}")
async def get_deployment(
    deployment_id: str,
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """Get full deployment status including step log."""
    result = await db.execute(
        select(WorkforceDeployment).where(
            (WorkforceDeployment.id == deployment_id) &
            (WorkforceDeployment.tenant_id == tenant_id)
        )
    )
    d = result.scalar_one_or_none()
    if not d:
        raise HTTPException(status_code=404, detail="Deployment not found")

    return {
        "id": d.id,
        "department_id": d.department_id,
        "domain_pack_id": d.domain_pack_id,
        "domain_pack_slug": d.domain_pack_slug,
        "status": d.status.value if isinstance(d.status, DeploymentStatus) else d.status,
        "current_step": d.current_step,
        "progress_pct": d.progress_pct,
        "selected_capabilities": d.selected_capabilities or [],
        "connected_systems": d.connected_systems or [],
        "employee_count": d.employee_count,
        "deployment_steps": d.deployment_steps or [],
        "agents_created": d.agents_created or [],
        "blueprints_created": d.blueprints_created or [],
        "capabilities_activated": d.capabilities_activated or [],
        "processes_created": d.processes_created or [],
        "error_log": d.error_log or [],
        "deployment_options": d.deployment_options or {},
        "started_at": str(d.started_at) if d.started_at else None,
        "completed_at": str(d.completed_at) if d.completed_at else None,
    }


@router.post("/start")
async def start_deployment(
    req: DeploymentCreateRequest,
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """Start a new department deployment. Creates the state machine record."""
    from app.workforce.deployment.studio import DeploymentStudio
    config = {
        "capabilities": req.selected_capabilities,
        "systems": req.connected_systems,
        "employee_count": req.employee_count,
    }
    dep_id = await DeploymentStudio.start_deployment_workflow(
        db=db,
        tenant_id=tenant_id,
        pack_id=req.domain_pack_id,
        config=config
    )
    result = await db.execute(
        select(WorkforceDeployment).where(WorkforceDeployment.id == dep_id)
    )
    deployment = result.scalar_one()
    return {
        "id": deployment.id,
        "status": deployment.status.value if isinstance(deployment.status, DeploymentStatus) else deployment.status,
        "message": "Deployment initiated in the background.",
    }


@router.post("/{deployment_id}/advance")
async def advance_deployment(
    deployment_id: str,
    req: DeploymentAdvanceRequest,
    db: AsyncSession = Depends(get_db),
):
    """Advance the deployment to the next state. Uses the DeploymentStateMachine."""
    result = await db.execute(
        select(WorkforceDeployment).where(WorkforceDeployment.id == deployment_id)
    )
    deployment = result.scalar_one_or_none()
    if not deployment:
        raise HTTPException(status_code=404, detail="Deployment not found")

    # Since the deployment pipeline runs in the background, this is a no-op
    # that simply returns the current state of the deployment.
    return {
        "id": deployment.id,
        "status": deployment.status.value if isinstance(deployment.status, DeploymentStatus) else deployment.status,
        "current_step": deployment.current_step,
        "progress_pct": deployment.progress_pct,
        "deployment_steps": deployment.deployment_steps or [],
    }
