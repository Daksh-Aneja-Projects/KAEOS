"""
KAEOS Operations Domain — V1 API Router
CRUD and agent triggers.
"""
from app.core.tenant import get_tenant_id, require_role
from app.core.audit import record_security_event
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func as sqlfunc

from app.core.database import get_db

# Models
from app.operations.models.core import OpsTeamMember
from app.operations.models.projects import Project, Task, ProjectStatus
from app.operations.models.resources import Resource, ResourceAllocation
from app.operations.models.vendors import VendorContract
from app.operations.models.procurement import PurchaseRequest, ProcurementStatus
from app.operations.models.quality import Inspection, QualityStatus

# Agents
from app.operations.agents.project_agent import ProjectAgent
from app.operations.agents.resource_agent import ResourceAgent
from app.operations.agents.vendor_agent import VendorAgent
from app.operations.agents.procurement_agent import ProcurementAgent
from app.operations.agents.qa_agent import QAAgent

import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/operations", tags=["Operations"])

# --- Dashboard ---
@router.get("/dashboard")
async def operations_dashboard(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    # Active Projects
    project_q = await db.execute(
        select(sqlfunc.count()).select_from(Project).where(Project.tenant_id == tenant_id)
        .where(Project.status == ProjectStatus.ACTIVE)
    )
    active_projects = project_q.scalar() or 0

    # Blocked/Warning Tasks
    blocked_q = await db.execute(
        select(sqlfunc.count()).select_from(Task).where(Task.tenant_id == tenant_id)
        .where(Task.status != "DONE")
        .where(Task.ai_risk_assessment.isnot(None))
    )
    blocked_tasks = blocked_q.scalar() or 0

    # Procurement Pending
    proc_q = await db.execute(
        select(sqlfunc.count()).select_from(PurchaseRequest).where(PurchaseRequest.tenant_id == tenant_id)
        .where(PurchaseRequest.status == ProcurementStatus.PENDING_APPROVAL)
    )
    pending_purchases = proc_q.scalar() or 0

    # Inspection Failures
    insp_q = await db.execute(
        select(sqlfunc.count()).select_from(Inspection).where(Inspection.tenant_id == tenant_id)
        .where(Inspection.status == QualityStatus.FAILED)
    )
    inspection_failures = insp_q.scalar() or 0

    return {
        "active_projects": active_projects,
        "blocked_tasks": blocked_tasks,
        "pending_purchases": pending_purchases,
        "failed_inspections": inspection_failures
    }

# --- Projects ---
@router.get("/projects")
async def list_projects(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    q = await db.execute(select(Project).where(Project.tenant_id == tenant_id).limit(200))
    projects = q.scalars().all()
    
    project_list = []
    for p in projects:
        manager_name = None
        if p.project_manager_id:
            mgr_q = await db.execute(select(OpsTeamMember).where(
                OpsTeamMember.id == p.project_manager_id, OpsTeamMember.tenant_id == tenant_id))
            mgr = mgr_q.scalar_one_or_none()
            manager_name = mgr.name if mgr else None

        # Labor cost to date — allocated hours × the resource's hourly rate.
        # The Project model carries no budget column, so budget stays None
        # and the UI renders "—" rather than a fake $0.
        allocs = (await db.execute(
            select(ResourceAllocation).where(
                ResourceAllocation.project_id == p.id,
                ResourceAllocation.tenant_id == tenant_id)
        )).scalars().all()
        spent = 0.0
        for a in allocs:
            res = (await db.execute(
                select(Resource).where(
                    Resource.id == a.resource_id, Resource.tenant_id == tenant_id)
            )).scalar_one_or_none()
            if res:
                spent += float(a.allocated_hours or 0) * float(res.cost_per_hour or 0)

        project_list.append({
            "id": p.id,
            "name": p.name,
            "status": p.status.value if hasattr(p.status, 'value') else str(p.status),
            "owner": manager_name,
            "budget": None,
            "spent": round(spent, 2),
            "completion_pct": float(p.completion_percentage or 0),
            "start_date": str(p.start_date) if p.start_date else None,
            "end_date": str(p.end_date) if p.end_date else None,
        })
    return project_list

@router.post("/projects/tasks/{task_id}/evaluate")
async def evaluate_task(task_id: str, tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db)):
    tenant_id = tenant["tenant_id"]
    # Callers (UI + e2e) pass a PROJECT id here; ProjectAgent evaluates projects.
    # Path kept for backward compatibility.
    agent = ProjectAgent()
    try:
        result = await agent.evaluate_project(db, task_id, tenant_id)
        await record_security_event(
            tenant_id=tenant_id, event_type="MODIFICATION", action="EXECUTE",
            actor=tenant.get("name"), actor_role=tenant.get("role"),
            resource_type="project", resource_id=task_id,
        )
        return result
    except ValueError as e:
        raise HTTPException(404, detail=str(e))
    except Exception as e:
        logger.exception("%s failed", __name__)
        raise HTTPException(500, detail="Internal error - see server logs") from e

# --- Resources ---
@router.get("/resources")
async def list_resources(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    q = await db.execute(select(ResourceAllocation).where(ResourceAllocation.tenant_id == tenant_id).limit(200))
    allocs = q.scalars().all()
    
    alloc_list = []
    for a in allocs:
        res_q = await db.execute(select(Resource).where(
            Resource.id == a.resource_id, Resource.tenant_id == tenant_id))
        res = res_q.scalar()
        project_name = None
        if a.project_id:
            proj_q = await db.execute(select(Project).where(
                Project.id == a.project_id, Project.tenant_id == tenant_id))
            proj = proj_q.scalar_one_or_none()
            project_name = proj.name if proj else None
        if res:
            alloc_list.append({
                "id": a.id,
                "name": res.name,
                "type": res.resource_type,
                "project": project_name,
                "utilization": float(a.utilization_percentage or 0),
                "available_from": res.is_available.isoformat() if res.is_available else None,
            })
    return alloc_list

@router.post("/resources/allocations/{allocation_id}/check")
async def check_overload(allocation_id: str, tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db)):
    tenant_id = tenant["tenant_id"]
    agent = ResourceAgent()
    try:
        result = await agent.check_overload(db, allocation_id, tenant_id)
        await record_security_event(
            tenant_id=tenant_id, event_type="MODIFICATION", action="EXECUTE",
            actor=tenant.get("name"), actor_role=tenant.get("role"),
            resource_type="resource_allocation", resource_id=allocation_id,
        )
        return result
    except ValueError as e:
        raise HTTPException(404, detail=str(e))
    except Exception as e:
        logger.exception("%s failed", __name__)
        raise HTTPException(500, detail="Internal error - see server logs") from e

# --- Vendors ---
@router.get("/vendors")
async def list_vendors(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    q = await db.execute(select(VendorContract).where(VendorContract.tenant_id == tenant_id).limit(200))
    contracts = q.scalars().all()
    return [{
        "id": c.id,
        "name": c.vendor_name,
        "category": c.service_provided,
        "risk_level": getattr(c, 'risk_level', 'MEDIUM') or 'MEDIUM',
        "contract_value": float(c.contract_value or 0),
        "soc2_verified": bool(getattr(c, 'soc2_verified', False)),
        "contract_expiry": str(c.renewal_date) if c.renewal_date else None,
    } for c in contracts]

@router.post("/vendors/{contract_id}/evaluate")
async def evaluate_vendor(contract_id: str, tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db)):
    tenant_id = tenant["tenant_id"]
    agent = VendorAgent()
    try:
        result = await agent.evaluate_vendor(db, contract_id, tenant_id)
        await record_security_event(
            tenant_id=tenant_id, event_type="MODIFICATION", action="EXECUTE",
            actor=tenant.get("name"), actor_role=tenant.get("role"),
            resource_type="vendor_contract", resource_id=contract_id,
        )
        return result
    except ValueError as e:
        raise HTTPException(404, detail=str(e))
    except Exception as e:
        logger.exception("%s failed", __name__)
        raise HTTPException(500, detail="Internal error - see server logs") from e

# --- Procurement ---
@router.get("/procurements")
async def list_procurements(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    from app.operations.models.procurement import PurchaseOrder
    q = await db.execute(select(PurchaseRequest).where(PurchaseRequest.tenant_id == tenant_id).limit(200))
    requests = q.scalars().all()
    result = []
    for r in requests:
        vendor = None
        po_q = await db.execute(select(PurchaseOrder).where(
            PurchaseOrder.tenant_id == tenant_id, PurchaseOrder.purchase_request_id == r.id))
        po = po_q.scalars().first()
        if po:
            vendor = po.vendor_name
        result.append({
            "id": r.id,
            "description": r.item_description,
            "requestor": r.requested_by,
            "status": r.status.value if hasattr(r.status, 'value') else str(r.status),
            "amount": float(r.total_estimated_cost or 0),
            "vendor": vendor,
            "submitted_at": str(getattr(r, 'created_at', '') or ''),
        })
    return result

@router.post("/procurements/{request_id}/audit")
async def audit_procurement(request_id: str, tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db)):
    tenant_id = tenant["tenant_id"]
    agent = ProcurementAgent()
    try:
        result = await agent.audit_request(db, request_id, tenant_id)
        await record_security_event(
            tenant_id=tenant_id, event_type="MODIFICATION", action="EXECUTE",
            actor=tenant.get("name"), actor_role=tenant.get("role"),
            resource_type="purchase_request", resource_id=request_id,
        )
        return result
    except ValueError as e:
        raise HTTPException(404, detail=str(e))
    except Exception as e:
        logger.exception("%s failed", __name__)
        raise HTTPException(500, detail="Internal error - see server logs") from e

# --- Quality ---
@router.get("/inspections")
async def list_inspections(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    from app.operations.models.quality import NonConformance, QualityStandard
    q = await db.execute(select(Inspection).where(Inspection.tenant_id == tenant_id).limit(200))
    inspections = q.scalars().all()
    result = []
    for i in inspections:
        nc_q = await db.execute(select(NonConformance).where(
            NonConformance.tenant_id == tenant_id, NonConformance.inspection_id == i.id))
        defects = len(nc_q.scalars().all())
        standard = (await db.execute(
            select(QualityStandard).where(
                QualityStandard.id == i.standard_id, QualityStandard.tenant_id == tenant_id)
        )).scalar_one_or_none()
        status_val = i.status.value if hasattr(i.status, 'value') else str(i.status)
        score = 100 if status_val == "PASSED" else (50 if status_val == "IN_PROGRESS" else 20)
        result.append({
            "id": i.id,
            "title": i.inspected_item,
            "area": standard.name if standard else None,
            "status": status_val,
            "score": score,
            "defects": defects,
            "inspector": i.inspector,
            "date": str(getattr(i, 'created_at', '') or '').split('T')[0] or None,
        })
    return result

@router.post("/inspections/{inspection_id}/audit")
async def audit_inspection(inspection_id: str, tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db)):
    tenant_id = tenant["tenant_id"]
    agent = QAAgent()
    try:
        result = await agent.inspect_qa(db, inspection_id, tenant_id)
        await record_security_event(
            tenant_id=tenant_id, event_type="MODIFICATION", action="EXECUTE",
            actor=tenant.get("name"), actor_role=tenant.get("role"),
            resource_type="inspection", resource_id=inspection_id,
        )
        return result
    except ValueError as e:
        raise HTTPException(404, detail=str(e))
    except Exception as e:
        logger.exception("%s failed", __name__)
        raise HTTPException(500, detail="Internal error - see server logs") from e

# ═══════════════════════════════════════════════════════════════════════
# Analytics & Workflow Layer (shared engine: app.core.workflow)
# ═══════════════════════════════════════════════════════════════════════
from typing import Optional  # noqa: E402
from app.core.workflow import (  # noqa: E402
    BulkTransitionRequest, TransitionRequest, apply_bulk_transition,
    apply_transition, list_workflow_events,
)
from app.operations.services.analytics import operations_analytics  # noqa: E402
from app.operations.services.workflows import SPECS as WORKFLOW_SPECS  # noqa: E402


@router.get("/analytics")
async def get_operations_analytics(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    """Computed procurement, quality and utilization KPIs for the ops cockpit."""
    return await operations_analytics(db, tenant_id)


@router.get("/workflows")
async def get_operations_workflows(tenant_id: str = Depends(get_tenant_id)):
    """Declared state machines - the frontend renders procurement actions from this."""
    return {name: spec.describe() for name, spec in WORKFLOW_SPECS.items()}


@router.get("/workflow-events")
async def get_operations_workflow_events(
    entity_type: Optional[str] = None, entity_id: Optional[str] = None,
    tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db),
):
    """Tenant-scoped transition audit trail for operations entities."""
    return await list_workflow_events(db, tenant_id, domain="operations",
                                      entity_type=entity_type, entity_id=entity_id)


@router.post("/purchase-requests/{request_id}/transition")
async def transition_purchase_request(
    request_id: str, body: TransitionRequest,
    tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db),
):
    """Move a purchase request through draft, approval, ordered, received."""
    return await apply_transition(db, WORKFLOW_SPECS["purchase_request"], request_id,
                                  body.to_state, tenant, note=body.note)


@router.post("/purchase-orders/{order_id}/transition")
async def transition_purchase_order(
    order_id: str, body: TransitionRequest,
    tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db),
):
    """Move a PO through approval, ordered, received (or cancel)."""
    return await apply_transition(db, WORKFLOW_SPECS["purchase_order"], order_id,
                                  body.to_state, tenant, note=body.note)

# ═══════════════════════════════════════════════════════════════════════
# Entity Creation
# ═══════════════════════════════════════════════════════════════════════
from pydantic import BaseModel, Field  # noqa: E402


class PurchaseRequestCreate(BaseModel):
    item_description: str = Field(..., min_length=1, max_length=256)
    quantity: int = Field(1, ge=1)
    unit_price: float = Field(0, ge=0)
    department: Optional[str] = Field(None, max_length=64)
    requested_by: Optional[str] = Field(None, max_length=128)


@router.post("/purchase-requests", status_code=201)
async def create_purchase_request(
    body: PurchaseRequestCreate,
    tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db),
):
    """File a purchase request (starts DRAFT; move via /transition)."""
    tenant_id = tenant["tenant_id"]
    pr = PurchaseRequest(
        tenant_id=tenant_id,
        item_description=body.item_description,
        quantity=body.quantity,
        unit_price=body.unit_price,
        total_estimated_cost=body.quantity * body.unit_price,
        department=body.department,
        requested_by=body.requested_by or tenant.get("name"),
    )
    db.add(pr)
    await db.commit()
    await db.refresh(pr)
    await record_security_event(
        tenant_id=tenant_id, event_type="MODIFICATION", action="WRITE",
        actor=tenant.get("name"), actor_role=tenant.get("role"),
        resource_type="purchase_request", resource_id=pr.id,
    )
    return {"id": pr.id, "item_description": pr.item_description,
            "status": pr.status.value if hasattr(pr.status, "value") else str(pr.status),
            "total_estimated_cost": float(pr.total_estimated_cost or 0)}


@router.post("/workflows/{entity_type}/bulk-transition")
async def bulk_transition_operations(
    entity_type: str, body: BulkTransitionRequest,
    tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db),
):
    """Apply one transition to up to 200 operations entities; per-id outcomes."""
    spec = WORKFLOW_SPECS.get(entity_type)
    if not spec:
        raise HTTPException(404, detail=f"Unknown workflow entity '{entity_type}'. Known: {sorted(WORKFLOW_SPECS)}")
    return await apply_bulk_transition(db, spec, body.ids, body.to_state, tenant, note=body.note)
