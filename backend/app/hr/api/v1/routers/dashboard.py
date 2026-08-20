"""KAEOS HR V1 — dashboard

The HR cockpit reads: the two list endpoints the dashboard leans on, the
dashboard aggregate itself and the shared-shape analytics payload.
"""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.tenant import get_tenant_id
from app.hr.models.performance import PerformanceReview
from app.hr.models.time_attendance import TimeOffRequest
from app.hr.services.analytics import hr_analytics, hr_dashboard

router = APIRouter()


# ── Time & Attendance / Performance (reads) ───────────────────────────────────

@router.get("/time-off-requests")
async def list_time_off_requests(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    q = await db.execute(select(TimeOffRequest).where(TimeOffRequest.tenant_id == tenant_id).limit(200))
    requests = q.scalars().all()
    return [{
        "id": r.id, "employee_id": r.employee_id, "status": r.status, "leave_type": r.leave_type,
        "start_date": r.start_date.isoformat() if r.start_date else None,
        "end_date": r.end_date.isoformat() if r.end_date else None,
        "hours_requested": r.hours_requested,
    } for r in requests]


@router.get("/performance-reviews")
async def list_performance_reviews(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    q = await db.execute(select(PerformanceReview).where(PerformanceReview.tenant_id == tenant_id).limit(200))
    reviews = q.scalars().all()
    return [{"id": r.id, "employee_id": r.employee_id, "status": r.status,
             "manager_rating": r.manager_rating, "self_rating": r.self_rating} for r in reviews]


# ── Dashboard ─────────────────────────────────────────────────────────────────

@router.get("/dashboard")
async def get_hr_dashboard(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    return await hr_dashboard(db, tenant_id)


# ── Analytics ────────────────────────────────────────────────────────────────

@router.get("/analytics")
async def get_hr_analytics(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    """Computed headcount, funnel and time-off KPIs for the HR cockpit."""
    return await hr_analytics(db, tenant_id)
