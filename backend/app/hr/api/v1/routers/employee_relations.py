"""KAEOS HR V1 — employee relations

Employee relations cases and the gated severity/risk triage.
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import record_security_event
from app.core.database import get_db
from app.core.department_endpoints import get_or_404
from app.core.tenant import approver_identity, get_tenant_id, require_role
from app.core.workflow import TransitionRequest, apply_transition
from app.hr.models.employee_relations import ERCase, CaseStatus
from app.hr.services.workflows import SPECS as WORKFLOW_SPECS

router = APIRouter()


# ── Employee Relations ─────────────────────────────────────────────────────────

class ERCaseCreate(BaseModel):
    title: str
    description: str
    reporter_id: Optional[str] = None
    accused_id: Optional[str] = None
    category: str = Field(..., pattern="^(HARASSMENT|POLICY_VIOLATION|DISPUTE|DISCRIMINATION|SAFETY|OTHER)$")
    severity: str = Field("MEDIUM", pattern="^(LOW|MEDIUM|HIGH|CRITICAL)$")


@router.get("/er-cases")
async def list_er_cases(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(
        select(ERCase).where(ERCase.tenant_id == tenant_id).order_by(ERCase.opened_at.desc()).limit(200)
    )).scalars().all()
    return [{
        "id": c.id, "title": c.title, "category": c.category,
        "status": c.status.value if hasattr(c.status, "value") else str(c.status),
        "severity": c.severity.value if hasattr(c.severity, "value") else str(c.severity),
        "reporter_id": c.reporter_id, "accused_id": c.accused_id, "investigator_id": c.investigator_id,
        "ai_risk_assessment": c.ai_risk_assessment, "ai_recommended_actions": c.ai_recommended_actions or [],
        "opened_at": c.opened_at.isoformat() if c.opened_at else None,
    } for c in rows]


@router.post("/er-cases", status_code=201)
async def create_er_case(
    body: ERCaseCreate, tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db),
):
    tenant_id = tenant["tenant_id"]
    case = ERCase(
        tenant_id=tenant_id, title=body.title, description=body.description,
        reporter_id=body.reporter_id, accused_id=body.accused_id,
        category=body.category, severity=body.severity, status=CaseStatus.OPEN,
    )
    db.add(case)
    await db.commit()
    await db.refresh(case)
    await record_security_event(tenant_id=tenant_id, event_type="MODIFICATION", action="WRITE",
        actor=approver_identity(tenant), actor_role=tenant.get("role"), resource_type="er_case", resource_id=case.id)
    return {"id": case.id, "status": case.status.value}


@router.post("/er-cases/{case_id}/transition")
async def transition_er_case(
    case_id: str, body: TransitionRequest,
    tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db),
):
    result = await apply_transition(db, WORKFLOW_SPECS["er_case"], case_id, body.to_state, tenant, note=body.note)
    if body.to_state == "CLOSED":
        case = (await db.execute(select(ERCase).where(
            ERCase.id == case_id, ERCase.tenant_id == tenant["tenant_id"]))).scalar_one_or_none()
        if case:
            case.closed_at = datetime.now(timezone.utc)
            db.add(case)
            await db.commit()
    return result


@router.post("/er-cases/{case_id}/triage")
async def triage_er_case(
    case_id: str, tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db),
):
    """Run the Employee Relations Agent's severity/risk triage through the
    gated 7-gate pipeline (EEOC + GDPR). Wires EmployeeRelationsAgent,
    previously bound only to dead org-graph metadata."""
    tenant_id = tenant["tenant_id"]
    await get_or_404(db, ERCase, case_id, tenant_id, detail="ER case not found")
    from app.hr.agents.employee_relations_agent import EmployeeRelationsAgent
    agent = EmployeeRelationsAgent()
    result = await agent.triage_case(db, case_id)
    await record_security_event(tenant_id=tenant_id, event_type="MODIFICATION", action="EXECUTE",
        actor=approver_identity(tenant), actor_role=tenant.get("role"), resource_type="er_case", resource_id=case_id,
        details={"status": result.get("status")})
    return {"case_id": case_id, **result}
