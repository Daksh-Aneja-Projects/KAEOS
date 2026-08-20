"""KAEOS HR V1 — interviews

Interview scheduling and interviewer feedback.
"""
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import record_security_event
from app.core.database import get_db
from app.core.department_endpoints import get_or_404
from app.core.tenant import approver_identity, get_tenant_id, require_role
from app.hr.models.core import HREmployee
from app.hr.models.recruiting import (
    Candidate, Interview,
)

router = APIRouter()


# ── Interviews (Recruiting) ────────────────────────────────────────────────────

class InterviewCreate(BaseModel):
    candidate_id: str
    interviewer_id: str
    scheduled_at: datetime
    duration_mins: int = Field(60, gt=0)
    interview_type: str = Field(..., max_length=64)


@router.get("/interviews")
async def list_interviews(
    candidate_id: Optional[str] = None,
    tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db),
):
    stmt = select(Interview).where(Interview.tenant_id == tenant_id)
    if candidate_id:
        stmt = stmt.where(Interview.candidate_id == candidate_id)
    rows = (await db.execute(stmt.order_by(Interview.scheduled_at.desc()).limit(200))).scalars().all()
    return [{
        "id": i.id, "candidate_id": i.candidate_id, "interviewer_id": i.interviewer_id,
        "scheduled_at": i.scheduled_at.isoformat() if i.scheduled_at else None,
        "duration_mins": i.duration_mins, "interview_type": i.interview_type,
        "feedback_submitted": i.feedback_submitted, "score": i.score, "recommendation": i.recommendation,
        "notes": i.notes,
    } for i in rows]


@router.post("/interviews", status_code=201)
async def schedule_interview(
    body: InterviewCreate, tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db),
):
    tenant_id = tenant["tenant_id"]
    await get_or_404(db, Candidate, body.candidate_id, tenant_id, detail="Candidate not found")
    await get_or_404(db, HREmployee, body.interviewer_id, tenant_id, detail="Interviewer not found")
    interview = Interview(
        tenant_id=tenant_id, candidate_id=body.candidate_id, interviewer_id=body.interviewer_id,
        scheduled_at=body.scheduled_at, duration_mins=body.duration_mins, interview_type=body.interview_type,
    )
    db.add(interview)
    await db.commit()
    await db.refresh(interview)
    await record_security_event(tenant_id=tenant_id, event_type="MODIFICATION", action="WRITE",
        actor=approver_identity(tenant), actor_role=tenant.get("role"), resource_type="interview", resource_id=interview.id)
    return {"id": interview.id, "scheduled_at": interview.scheduled_at.isoformat()}


class InterviewFeedback(BaseModel):
    score: int = Field(..., ge=1, le=5)
    recommendation: str = Field(..., pattern="^(STRONG_HIRE|HIRE|NO_HIRE|STRONG_NO_HIRE)$")
    notes: Optional[str] = Field(None, max_length=2000)


@router.post("/interviews/{interview_id}/feedback")
async def submit_interview_feedback(
    interview_id: str, body: InterviewFeedback,
    tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db),
):
    tenant_id = tenant["tenant_id"]
    interview = await get_or_404(db, Interview, interview_id, tenant_id, detail="Interview not found")
    interview.score = body.score
    interview.recommendation = body.recommendation
    interview.notes = body.notes
    interview.feedback_submitted = True
    db.add(interview)
    await db.commit()
    await record_security_event(tenant_id=tenant_id, event_type="MODIFICATION", action="WRITE",
        actor=approver_identity(tenant), actor_role=tenant.get("role"), resource_type="interview", resource_id=interview_id)
    return {"id": interview_id, "feedback_submitted": True, "recommendation": interview.recommendation}
