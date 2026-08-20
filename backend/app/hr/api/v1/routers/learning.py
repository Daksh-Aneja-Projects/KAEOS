"""KAEOS HR V1 — learning

Learning and development: the course catalogue and enrollments.
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
from app.hr.models.core import HREmployee
from app.hr.models.learning import Course, CourseEnrollment
from app.hr.services.workflows import SPECS as WORKFLOW_SPECS

router = APIRouter()


# ── Learning & Development ────────────────────────────────────────────────────

class CourseCreate(BaseModel):
    title: str
    description: Optional[str] = None
    provider: Optional[str] = None
    is_required_for_compliance: bool = False
    estimated_minutes: int = Field(60, gt=0)


@router.get("/courses")
async def list_courses(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(Course).where(Course.tenant_id == tenant_id).limit(200))).scalars().all()
    return [{
        "id": c.id, "title": c.title, "description": c.description, "provider": c.provider,
        "is_required_for_compliance": c.is_required_for_compliance, "estimated_minutes": c.estimated_minutes,
        "status": c.status.value if hasattr(c.status, "value") else str(c.status),
    } for c in rows]


@router.post("/courses", status_code=201)
async def create_course(
    body: CourseCreate, tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db),
):
    tenant_id = tenant["tenant_id"]
    course = Course(
        tenant_id=tenant_id, title=body.title, description=body.description, provider=body.provider,
        is_required_for_compliance=body.is_required_for_compliance, estimated_minutes=body.estimated_minutes,
    )
    db.add(course)
    await db.commit()
    await db.refresh(course)
    await record_security_event(tenant_id=tenant_id, event_type="MODIFICATION", action="WRITE",
        actor=approver_identity(tenant), actor_role=tenant.get("role"), resource_type="course", resource_id=course.id)
    return {"id": course.id, "title": course.title}


class CourseEnrollmentCreate(BaseModel):
    employee_id: str
    course_id: str
    due_date: Optional[datetime] = None


@router.get("/course-enrollments")
async def list_course_enrollments(
    employee_id: Optional[str] = None,
    tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db),
):
    stmt = select(CourseEnrollment).where(CourseEnrollment.tenant_id == tenant_id)
    if employee_id:
        stmt = stmt.where(CourseEnrollment.employee_id == employee_id)
    rows = (await db.execute(stmt.limit(200))).scalars().all()
    return [{
        "id": e.id, "employee_id": e.employee_id, "course_id": e.course_id,
        "status": e.status.value if hasattr(e.status, "value") else str(e.status),
        "progress_pct": e.progress_pct, "due_date": e.due_date.isoformat() if e.due_date else None,
        "completed_at": e.completed_at.isoformat() if e.completed_at else None,
    } for e in rows]


@router.post("/course-enrollments", status_code=201)
async def create_course_enrollment(
    body: CourseEnrollmentCreate, tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db),
):
    tenant_id = tenant["tenant_id"]
    await get_or_404(db, HREmployee, body.employee_id, tenant_id, detail="Employee not found")
    await get_or_404(db, Course, body.course_id, tenant_id, detail="Course not found")
    enrollment = CourseEnrollment(
        tenant_id=tenant_id, employee_id=body.employee_id, course_id=body.course_id, due_date=body.due_date,
    )
    db.add(enrollment)
    await db.commit()
    await db.refresh(enrollment)
    await record_security_event(tenant_id=tenant_id, event_type="MODIFICATION", action="WRITE",
        actor=approver_identity(tenant), actor_role=tenant.get("role"),
        resource_type="course_enrollment", resource_id=enrollment.id)
    return {"id": enrollment.id, "status": enrollment.status.value}


@router.post("/course-enrollments/{enrollment_id}/transition")
async def transition_course_enrollment(
    enrollment_id: str, body: TransitionRequest,
    tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db),
):
    result = await apply_transition(db, WORKFLOW_SPECS["course_enrollment"], enrollment_id,
                                    body.to_state, tenant, note=body.note)
    if body.to_state == "COMPLETED":
        enrollment = (await db.execute(select(CourseEnrollment).where(
            CourseEnrollment.id == enrollment_id, CourseEnrollment.tenant_id == tenant["tenant_id"],
        ))).scalar_one_or_none()
        if enrollment:
            enrollment.progress_pct = 100.0
            enrollment.completed_at = datetime.now(timezone.utc)
            db.add(enrollment)
            await db.commit()
    return result
