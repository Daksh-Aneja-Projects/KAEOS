"""
KAEOS Operations Domain — V1 API Router
CRUD and agent triggers.
"""
from app.core.tenant import get_tenant_id
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
    q = await db.execute(select(Project).where(Project.tenant_id == tenant_id))
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
async def evaluate_task(task_id: str, tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    # Callers (UI + e2e) pass a PROJECT id here; ProjectAgent evaluates projects.
    # Path kept for backward compatibility.
    agent = ProjectAgent()
    try:
        return await agent.evaluate_project(db, task_id, tenant_id)
    except ValueError as e:
        raise HTTPException(404, detail=str(e))
    except Exception as e:
        logger.exception("%s failed", __name__)
        raise HTTPException(500, detail="Internal error - see server logs") from e

# --- Resources ---
@router.get("/resources")
async def list_resources(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    q = await db.execute(select(ResourceAllocation).where(ResourceAllocation.tenant_id == tenant_id))
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
async def check_overload(allocation_id: str, tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    agent = ResourceAgent()
    try:
        return await agent.check_overload(db, allocation_id, tenant_id)
    except ValueError as e:
        raise HTTPException(404, detail=str(e))
    except Exception as e:
        logger.exception("%s failed", __name__)
        raise HTTPException(500, detail="Internal error - see server logs") from e

# --- Vendors ---
@router.get("/vendors")
async def list_vendors(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    q = await db.execute(select(VendorContract).where(VendorContract.tenant_id == tenant_id))
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
async def evaluate_vendor(contract_id: str, tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    agent = VendorAgent()
    try:
        return await agent.evaluate_vendor(db, contract_id, tenant_id)
    except ValueError as e:
        raise HTTPException(404, detail=str(e))
    except Exception as e:
        logger.exception("%s failed", __name__)
        raise HTTPException(500, detail="Internal error - see server logs") from e

# --- Procurement ---
@router.get("/procurements")
async def list_procurements(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    from app.operations.models.procurement import PurchaseOrder
    q = await db.execute(select(PurchaseRequest).where(PurchaseRequest.tenant_id == tenant_id))
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
async def audit_procurement(request_id: str, tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    agent = ProcurementAgent()
    try:
        return await agent.audit_request(db, request_id, tenant_id)
    except ValueError as e:
        raise HTTPException(404, detail=str(e))
    except Exception as e:
        logger.exception("%s failed", __name__)
        raise HTTPException(500, detail="Internal error - see server logs") from e

# --- Quality ---
@router.get("/inspections")
async def list_inspections(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    from app.operations.models.quality import NonConformance, QualityStandard
    q = await db.execute(select(Inspection).where(Inspection.tenant_id == tenant_id))
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
async def audit_inspection(inspection_id: str, tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    agent = QAAgent()
    try:
        return await agent.inspect_qa(db, inspection_id, tenant_id)
    except ValueError as e:
        raise HTTPException(404, detail=str(e))
    except Exception as e:
        logger.exception("%s failed", __name__)
        raise HTTPException(500, detail="Internal error - see server logs") from e
