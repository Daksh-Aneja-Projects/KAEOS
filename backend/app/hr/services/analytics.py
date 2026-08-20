"""
KAEOS HR — Analytics Service
Headcount composition, recruiting funnel conversion, time-off load — all
computed live from tenant rows in the shared domain-analytics shape.

Also home to the two other read-models built from the same rows: the cockpit
dashboard aggregate (``hr_dashboard``) and the daily metric snapshot upsert
(``hr_metric_snapshot``). Both moved here from the V1 router so the SQL that
derives them sits with the rest of the HR analytics, not in an HTTP handler.
"""
from datetime import datetime, timezone
from typing import Any, Dict

from sqlalchemy import case, func as sqlfunc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.domain_analytics import DomainAnalytics
from app.hr.models.analytics import HRMetricSnapshot
from app.hr.models.core import EmploymentStatus, HREmployee
from app.hr.models.payroll import PayrollRun
from app.hr.models.recruiting import Candidate, CandidateStage, JobRequisition, ReqStatus
from app.hr.models.time_attendance import TimeOffRequest

_FUNNEL_ORDER = ["APPLIED", "AI_SCREENING", "RECRUITER_SCREEN", "HM_INTERVIEW",
                 "PANEL_INTERVIEW", "OFFER_PREP", "OFFER_EXTENDED", "HIRED"]


async def hr_analytics(db: AsyncSession, tenant_id: str, charts: bool = True) -> DomainAnalytics:
    """`charts=False` skips the series queries that feed no KPI and no insight,
    for callers (the org pulse) that read only kpis + insights."""
    # Headcount by employment status.
    emp_q = await db.execute(
        select(HREmployee.status, sqlfunc.count())
        .where(HREmployee.tenant_id == tenant_id)
        .group_by(HREmployee.status)
    )
    status_counts = {(s.value if hasattr(s, "value") else str(s)): int(c) for s, c in emp_q.all()}
    active = status_counts.get("ACTIVE", 0)
    total_emp = sum(status_counts.values())

    # Headcount by location (top 6) — chart-only.
    by_location: list[dict] = []
    if charts:
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
                         "message": f"{open_reqs} open requisitions with no offers extended yet; funnel may be top-heavy."})
    if status_counts.get("ONBOARDING", 0):
        insights.append({"severity": "info",
                         "message": f"{status_counts['ONBOARDING']} employees are in onboarding."})
    if not insights:
        insights.append({"severity": "info", "message": "HR pipeline is clear; no pending queues."})

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
        ] if charts else [],
        "insights": insights,
    }


async def hr_dashboard(db: AsyncSession, tenant_id: str) -> Dict[str, Any]:
    """The HR cockpit tiles. Moved verbatim from GET /hr/dashboard."""
    # Derivable metrics from real rows; the rest stay None ("—" in the UI)
    # until a genuine data source (surveys, LMS) exists. All counts are SQL
    # aggregates - no full-table loads.
    from datetime import datetime, timezone as _tz

    # Headcount by status, carrying terminated as a conditional sum: the OR
    # matters - an employee with a termination_date but a stale status must
    # still count, and a plain GROUP BY on status alone would undercount.
    emp_q = await db.execute(
        select(HREmployee.status, sqlfunc.count(),
               sqlfunc.coalesce(sqlfunc.sum(case(
                   ((HREmployee.status == EmploymentStatus.TERMINATED)
                    | (HREmployee.termination_date.isnot(None)), 1), else_=0)), 0))
        .where(HREmployee.tenant_id == tenant_id)
        .group_by(HREmployee.status)
    )
    total_employees, terminated = 0, 0
    for _s, count, term in emp_q.all():
        total_employees += int(count)
        terminated += int(term or 0)
    turnover_rate = round(terminated / total_employees * 100, 1) if total_employees else None

    # Recruiting funnel: one GROUP BY on stage.
    cand_q = await db.execute(
        select(Candidate.stage, sqlfunc.count())
        .where(Candidate.tenant_id == tenant_id)
        .group_by(Candidate.stage)
    )
    stage_counts = {(s.value if hasattr(s, "value") else str(s)): int(c) for s, c in cand_q.all()}
    total_candidates = sum(stage_counts.values())
    hired = stage_counts.get("HIRED", 0)
    offers_out = stage_counts.get("OFFER_EXTENDED", 0)
    offer_acceptance_rate = round(hired / (hired + offers_out) * 100, 1) if (hired + offers_out) else None

    open_reqs = int((await db.execute(
        select(sqlfunc.count())
        .where(JobRequisition.tenant_id == tenant_id,
               JobRequisition.status == ReqStatus.OPEN)
    )).scalar() or 0)

    now = datetime.now(_tz.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    applications_this_month = int((await db.execute(
        select(sqlfunc.count())
        .where(Candidate.tenant_id == tenant_id, Candidate.applied_at >= month_start)
    )).scalar() or 0)

    # Compliance: AVG over a 0/1 case is passed/total without loading the
    # (unbounded) fairness audit log.
    from app.models.fairness import FairnessAuditLog
    passed_ratio = (await db.execute(
        select(sqlfunc.avg(case((FairnessAuditLog.passed == True, 1.0), else_=0.0)))  # noqa: E712
        .where(FairnessAuditLog.tenant_id == tenant_id)
    )).scalar()
    compliance_score = round(float(passed_ratio) * 100, 1) if passed_ratio is not None else None

    return {
        "total_employees": total_employees,
        "open_positions": open_reqs,
        "total_candidates": total_candidates,
        "applications_this_month": applications_this_month,
        "avg_time_to_fill": None,
        "offer_acceptance_rate": offer_acceptance_rate,
        "satisfaction_score": None,
        "turnover_rate": turnover_rate,
        "training_completion": None,
        "compliance_score": compliance_score,
    }


async def hr_metric_snapshot(db: AsyncSession, tenant_id: str) -> HRMetricSnapshot:
    """Compute today's HR metric snapshot from real current rows (upserts if
    one already exists for today). Fields with no real data source (e.g.
    voluntary vs involuntary turnover split — HREmployee has no termination
    reason) stay null rather than a fabricated number."""
    today = datetime.now(timezone.utc).date()

    # SQL counts; only the HIRED candidates are loaded as rows, because the
    # time-to-fill date-diff stays in Python (a SQL date-diff would need
    # julianday on SQLite vs extract/epoch on Postgres).
    total_headcount, active_contractors = (
        int(v or 0) for v in (await db.execute(
            select(sqlfunc.count(),
                   sqlfunc.coalesce(sqlfunc.sum(case(
                       (HREmployee.status == EmploymentStatus.CONTRACTOR, 1), else_=0)), 0))
            .where(HREmployee.tenant_id == tenant_id)
        )).one()
    )
    open_reqs = int((await db.execute(
        select(sqlfunc.count())
        .where(JobRequisition.tenant_id == tenant_id,
               JobRequisition.status == ReqStatus.OPEN)
    )).scalar() or 0)
    offers_out = int((await db.execute(
        select(sqlfunc.count())
        .where(Candidate.tenant_id == tenant_id,
               Candidate.stage == CandidateStage.OFFER_EXTENDED)
    )).scalar() or 0)
    hired = (await db.execute(
        select(Candidate).where(Candidate.tenant_id == tenant_id,
                                Candidate.stage == CandidateStage.HIRED)
    )).scalars().all()
    offer_acceptance_rate = round(len(hired) / (len(hired) + offers_out) * 100, 1) if (hired or offers_out) else None
    fill_days = [
        (c.updated_at - c.applied_at).days for c in hired
        if c.updated_at and c.applied_at and (c.updated_at - c.applied_at).days >= 0
    ]
    time_to_fill = round(sum(fill_days) / len(fill_days), 1) if fill_days else None

    latest_run = (await db.execute(
        select(PayrollRun).where(PayrollRun.tenant_id == tenant_id).order_by(PayrollRun.period_end.desc())
    )).scalars().first()
    payroll_run_rate = latest_run.total_gross if latest_run and latest_run.total_gross else None

    existing = (await db.execute(select(HRMetricSnapshot).where(
        HRMetricSnapshot.tenant_id == tenant_id, HRMetricSnapshot.snapshot_date == today,
    ))).scalar_one_or_none()
    snap = existing or HRMetricSnapshot(tenant_id=tenant_id, snapshot_date=today)
    snap.total_headcount = total_headcount
    snap.active_contractors = active_contractors
    snap.open_requisitions = open_reqs
    snap.offer_acceptance_rate = offer_acceptance_rate
    snap.time_to_fill_avg_days = time_to_fill
    snap.total_payroll_run_rate = payroll_run_rate
    db.add(snap)
    await db.commit()
    await db.refresh(snap)
    return snap
