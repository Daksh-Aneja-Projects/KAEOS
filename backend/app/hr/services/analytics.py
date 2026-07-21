"""
KAEOS HR — Analytics Service
Headcount composition, recruiting funnel conversion, time-off load — all
computed live from tenant rows in the shared domain-analytics shape.
"""
from sqlalchemy import func as sqlfunc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.hr.models.core import EmploymentStatus, HREmployee
from app.hr.models.recruiting import Candidate, CandidateStage, JobRequisition, ReqStatus
from app.hr.models.time_attendance import LeaveStatus, TimeOffRequest

_FUNNEL_ORDER = ["APPLIED", "AI_SCREENING", "RECRUITER_SCREEN", "HM_INTERVIEW",
                 "PANEL_INTERVIEW", "OFFER_PREP", "OFFER_EXTENDED", "HIRED"]


async def hr_analytics(db: AsyncSession, tenant_id: str) -> dict:
    # Headcount by employment status.
    emp_q = await db.execute(
        select(HREmployee.status, sqlfunc.count())
        .where(HREmployee.tenant_id == tenant_id)
        .group_by(HREmployee.status)
    )
    status_counts = {(s.value if hasattr(s, "value") else str(s)): int(c) for s, c in emp_q.all()}
    active = status_counts.get("ACTIVE", 0)
    total_emp = sum(status_counts.values())

    # Headcount by location (top 6).
    loc_q = await db.execute(
        select(sqlfunc.coalesce(HREmployee.location, "Unspecified"), sqlfunc.count())
        .where(HREmployee.tenant_id == tenant_id)
        .group_by(HREmployee.location)
        .order_by(sqlfunc.count().desc())
        .limit(6)
    )
    by_location = [{"label": l, "value": int(c)} for l, c in loc_q.all()]

    # Recruiting funnel.
    cand_q = await db.execute(
        select(Candidate.stage, sqlfunc.count())
        .where(Candidate.tenant_id == tenant_id)
        .group_by(Candidate.stage)
    )
    stage_counts = {(s.value if hasattr(s, "value") else str(s)): int(c) for s, c in cand_q.all()}
    funnel = [{"label": s.replace("_", " ").title(), "value": stage_counts.get(s, 0)}
              for s in _FUNNEL_ORDER]
    total_candidates = sum(stage_counts.values())
    hired = stage_counts.get("HIRED", 0)

    # Open requisitions.
    req_q = await db.execute(
        select(sqlfunc.count())
        .where(JobRequisition.tenant_id == tenant_id,
               JobRequisition.status == ReqStatus.OPEN)
    )
    open_reqs = int(req_q.scalar() or 0)

    # Time-off: pending queue and approval rate.
    to_q = await db.execute(
        select(TimeOffRequest.status, sqlfunc.count())
        .where(TimeOffRequest.tenant_id == tenant_id)
        .group_by(TimeOffRequest.status)
    )
    to_counts = {(s.value if hasattr(s, "value") else str(s)): int(c) for s, c in to_q.all()}
    pending_to = to_counts.get("REQUESTED", 0)
    decided = to_counts.get("APPROVED", 0) + to_counts.get("DENIED", 0)
    approval_rate = (to_counts.get("APPROVED", 0) / decided * 100) if decided else None

    insights = []
    if pending_to:
        insights.append({"severity": "warning",
                         "message": f"{pending_to} time-off requests are waiting for a decision."})
    if open_reqs and stage_counts.get("OFFER_EXTENDED", 0) == 0 and total_candidates:
        insights.append({"severity": "info",
                         "message": f"{open_reqs} open requisitions with no offers extended yet — funnel may be top-heavy."})
    if status_counts.get("ONBOARDING", 0):
        insights.append({"severity": "info",
                         "message": f"{status_counts['ONBOARDING']} employees are in onboarding."})
    if not insights:
        insights.append({"severity": "info", "message": "HR pipeline is clear — no pending queues."})

    return {
        "domain": "hr",
        "kpis": [
            {"key": "headcount", "label": "Total Headcount", "value": total_emp, "format": "number"},
            {"key": "active", "label": "Active Employees", "value": active, "format": "number"},
            {"key": "open_reqs", "label": "Open Requisitions", "value": open_reqs, "format": "number"},
            {"key": "candidates", "label": "Candidates in Funnel", "value": total_candidates - hired, "format": "number"},
            {"key": "pending_to", "label": "Pending Time-Off", "value": pending_to, "format": "number"},
            {"key": "to_approval", "label": "Time-Off Approval Rate", "value": approval_rate, "format": "percent"},
        ],
        "charts": [
            {"key": "funnel", "title": "Recruiting Funnel", "type": "funnel", "items": funnel},
            {"key": "emp_status", "title": "Headcount by Status", "type": "donut",
             "items": [{"label": k, "value": v} for k, v in status_counts.items()]},
            {"key": "by_location", "title": "Headcount by Location", "type": "bar", "items": by_location},
        ],
        "insights": insights,
    }
