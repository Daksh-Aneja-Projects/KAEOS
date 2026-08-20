"""KAEOS HR V1 — performance

Performance reviews: cycles, review creation, self/manager ratings and
the gated 360-feedback synthesis.
"""
from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import record_security_event
from app.core.database import get_db
from app.core.department_endpoints import get_or_404
from app.core.tenant import approver_identity, get_tenant_id, require_role
from app.core.workflow import TransitionRequest, apply_transition
from app.hr.api.v1.routers._shared import _exec_id
from app.hr.models.core import HREmployee
from app.hr.models.performance import PerformanceReview, ReviewCycle
from app.hr.services.workflows import SPECS as WORKFLOW_SPECS
from app.models.execution_status import ExecutionStatus

router = APIRouter()


def _workflow_event(tenant_id: str, entity_type: str, entity_id: str, from_state: str, to_state: str, tenant: dict):
    """A WorkflowEvent row for mutations that carry a richer payload than the
    generic engine's transition endpoint can express (a rating + assessment,
    not just a bare to_state) — same audit trail, hand-built instead of via
    apply_transition."""
    from app.core.workflow import WorkflowEvent
    return WorkflowEvent(
        tenant_id=tenant_id, domain="hr", entity_type=entity_type, entity_id=entity_id,
        from_state=from_state, to_state=to_state,
        actor=approver_identity(tenant), actor_role=tenant.get("role"),
    )


# ── Performance Reviews: cycles, creation, ratings, AI synthesis ───────────────

class ReviewCycleCreate(BaseModel):
    name: str
    start_date: datetime
    end_date: datetime


@router.get("/performance-cycles")
async def list_performance_cycles(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(
        select(ReviewCycle).where(ReviewCycle.tenant_id == tenant_id)
        .order_by(ReviewCycle.start_date.desc()).limit(100)
    )).scalars().all()
    return [{
        "id": c.id, "name": c.name, "start_date": c.start_date.isoformat() if c.start_date else None,
        "end_date": c.end_date.isoformat() if c.end_date else None, "is_active": c.is_active,
    } for c in rows]


@router.post("/performance-cycles", status_code=201)
async def create_performance_cycle(
    body: ReviewCycleCreate, tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db),
):
    tenant_id = tenant["tenant_id"]
    cycle = ReviewCycle(tenant_id=tenant_id, name=body.name, start_date=body.start_date, end_date=body.end_date)
    db.add(cycle)
    await db.commit()
    await db.refresh(cycle)
    await record_security_event(tenant_id=tenant_id, event_type="MODIFICATION", action="WRITE",
        actor=approver_identity(tenant), actor_role=tenant.get("role"), resource_type="review_cycle", resource_id=cycle.id)
    return {"id": cycle.id, "name": cycle.name}


class PerformanceReviewCreate(BaseModel):
    cycle_id: str
    employee_id: str
    reviewer_id: str


@router.post("/performance-reviews", status_code=201)
async def create_performance_review(
    body: PerformanceReviewCreate, tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db),
):
    tenant_id = tenant["tenant_id"]
    await get_or_404(db, ReviewCycle, body.cycle_id, tenant_id, detail="Review cycle not found")
    await get_or_404(db, HREmployee, body.employee_id, tenant_id, detail="Employee not found")
    await get_or_404(db, HREmployee, body.reviewer_id, tenant_id, detail="Reviewer not found")
    review = PerformanceReview(
        tenant_id=tenant_id, cycle_id=body.cycle_id, employee_id=body.employee_id,
        reviewer_id=body.reviewer_id, status="DRAFT",
    )
    db.add(review)
    await db.commit()
    await db.refresh(review)
    await record_security_event(tenant_id=tenant_id, event_type="MODIFICATION", action="WRITE",
        actor=approver_identity(tenant), actor_role=tenant.get("role"),
        resource_type="performance_review", resource_id=review.id)
    return {"id": review.id, "status": review.status}


@router.post("/performance-reviews/{review_id}/transition")
async def transition_performance_review(
    review_id: str, body: TransitionRequest,
    tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db),
):
    """Only DRAFT -> PENDING_EMPLOYEE moves through the generic engine; the
    two steps after that always carry a rating payload, so they go through
    the self-rating/manager-rating endpoints instead (see WORKFLOW_SPECS)."""
    return await apply_transition(db, WORKFLOW_SPECS["performance_review"], review_id,
                                  body.to_state, tenant, note=body.note)


class RatingSubmit(BaseModel):
    rating: int = Field(..., ge=1, le=5)
    assessment: str = Field(..., max_length=4000)


@router.post("/performance-reviews/{review_id}/self-rating")
async def submit_self_rating(
    review_id: str, body: RatingSubmit,
    tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db),
):
    tenant_id = tenant["tenant_id"]
    review = await get_or_404(db, PerformanceReview, review_id, tenant_id, detail="Performance review not found")
    if review.status not in ("DRAFT", "PENDING_EMPLOYEE"):
        raise HTTPException(409, detail={"error": "invalid_transition", "from_state": review.status,
                                          "reason": "Self-rating can only be submitted from DRAFT or PENDING_EMPLOYEE."})
    from_state = review.status
    review.self_rating = body.rating
    review.self_assessment = body.assessment
    review.status = "PENDING_MANAGER"
    db.add(review)
    db.add(_workflow_event(tenant_id, "performance_review", review_id, from_state, "PENDING_MANAGER", tenant))
    await db.commit()
    await record_security_event(tenant_id=tenant_id, event_type="MODIFICATION", action="WRITE",
        actor=approver_identity(tenant), actor_role=tenant.get("role"),
        resource_type="performance_review", resource_id=review_id)
    return {"id": review_id, "status": review.status}


@router.post("/performance-reviews/{review_id}/manager-rating")
async def submit_manager_rating(
    review_id: str, body: RatingSubmit,
    tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db),
):
    tenant_id = tenant["tenant_id"]
    review = await get_or_404(db, PerformanceReview, review_id, tenant_id, detail="Performance review not found")
    if review.status != "PENDING_MANAGER":
        raise HTTPException(409, detail={"error": "invalid_transition", "from_state": review.status,
                                          "reason": "Manager rating can only be submitted from PENDING_MANAGER."})
    from_state = review.status
    review.manager_rating = body.rating
    review.manager_assessment = body.assessment
    review.status = "COMPLETED"
    db.add(review)
    db.add(_workflow_event(tenant_id, "performance_review", review_id, from_state, "COMPLETED", tenant))
    await db.commit()
    await record_security_event(tenant_id=tenant_id, event_type="MODIFICATION", action="WRITE",
        actor=approver_identity(tenant), actor_role=tenant.get("role"),
        resource_type="performance_review", resource_id=review_id)
    return {"id": review_id, "status": review.status}


class SynthesizeFeedbackBody(BaseModel):
    raw_feedback: List[str] = Field(..., min_length=1)


@router.post("/performance-reviews/{review_id}/synthesize-feedback")
async def synthesize_review_feedback(
    review_id: str, body: SynthesizeFeedbackBody,
    tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db),
):
    """Run the Performance Agent's 360-feedback synthesis, which persists
    ai_feedback_summary/ai_growth_areas directly onto the review. Wires
    PerformanceAgent, previously bound only to dead org-graph metadata."""
    tenant_id = tenant["tenant_id"]
    review = await get_or_404(db, PerformanceReview, review_id, tenant_id, detail="Performance review not found")
    from app.hr.agents.performance_agent import PerformanceAgent
    from app.hr.agents.gated_runner import extract_decision
    agent = PerformanceAgent()
    # Through the 7-gate pipeline (not the ungated agent method); persist the
    # synthesis onto the review only when the run cleared every gate.
    result = await agent.execute_via_pipeline(db, tenant_id, {
        "action": "synthesize_360_feedback",
        "raw_feedback": body.raw_feedback,
    })
    status = result.get("status")
    analysis = extract_decision(result) if status == ExecutionStatus.SUCCESS_CLEAN else {}
    if analysis:
        review.ai_feedback_summary = analysis.get("summary")
        review.ai_growth_areas = analysis.get("growth_areas", [])
        db.add(review)
        await db.commit()
    await record_security_event(tenant_id=tenant_id, event_type="MODIFICATION", action="EXECUTE",
        actor=approver_identity(tenant), actor_role=tenant.get("role"),
        resource_type="performance_review", resource_id=review_id)
    return {"review_id": review_id, "status": status, "analysis": analysis, "execution_id": _exec_id(result)}
