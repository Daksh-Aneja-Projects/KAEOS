"""
SQL == Python reconciliation for the dashboard aggregate rewrites.

The HR and Engineering dashboards (and the HR metric snapshot) were rewritten
from full-table loads to SQL aggregates. These tests seed rows that exercise
the two known traps - a termination_date-only terminated employee (status
never flipped) and a NULL-approvals pull request - then recount the SAME
session data with the original brute-force Python logic and assert the
endpoint numbers match exactly, rounding included.

Unit-level: SQLite in-memory via conftest's async_client/db fixtures; no LLM.
"""
from datetime import date, datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.engineering.models.core import Service, ServiceHealth
from app.engineering.models.delivery import DeployStatus, Deployment, PRStatus, PullRequest
from app.engineering.models.incidents import Incident, IncidentSeverity, IncidentStatus
from app.hr.models.core import EmploymentStatus, HREmployee
from app.hr.models.recruiting import Candidate, CandidateStage, JobRequisition, ReqStatus
from app.models.fairness import FairnessAuditLog

TENANT = "tenant_acme"  # dev-mode default tenant (app/core/tenant.py)


def _e(v):
    return v.value if hasattr(v, "value") else str(v)


@pytest.mark.asyncio
async def test_engineering_dashboard_matches_python_recount(async_client: AsyncClient, db: AsyncSession):
    db.add_all([
        Service(id="svc-h", tenant_id=TENANT, name="Payments", slug="payments",
                health=ServiceHealth.HEALTHY),
        Service(id="svc-d", tenant_id=TENANT, name="Identity", slug="identity",
                health=ServiceHealth.DEGRADED),
        # NULL approvals must count as awaiting review (coalesce, not raw ==0).
        PullRequest(id="pr-null", tenant_id=TENANT, number=1, title="null approvals",
                    status=PRStatus.OPEN, approvals=None),
        PullRequest(id="pr-rev", tenant_id=TENANT, number=2, title="has reviews",
                    status=PRStatus.IN_REVIEW, approvals=2),
        # Merged with zero approvals: NOT open, must not count as awaiting.
        PullRequest(id="pr-merged", tenant_id=TENANT, number=3, title="merged",
                    status=PRStatus.MERGED, approvals=0),
        Deployment(id="d-ok", tenant_id=TENANT, version="1.0", status=DeployStatus.SUCCEEDED),
        Deployment(id="d-fail", tenant_id=TENANT, version="1.1", status=DeployStatus.FAILED),
        Deployment(id="d-rb", tenant_id=TENANT, version="1.2", status=DeployStatus.ROLLED_BACK),
        Deployment(id="d-pend", tenant_id=TENANT, version="1.3", status=DeployStatus.PENDING_APPROVAL),
        Incident(id="i-open", tenant_id=TENANT, incident_number="INC-1", title="open sev1",
                 severity=IncidentSeverity.SEV1, status=IncidentStatus.DETECTED),
        Incident(id="i-res", tenant_id=TENANT, incident_number="INC-2", title="resolved",
                 severity=IncidentSeverity.SEV2, status=IncidentStatus.RESOLVED,
                 time_to_resolve_mins=120),
        # POSTMORTEM_DUE is still open AND counts toward postmortems_due.
        Incident(id="i-pm", tenant_id=TENANT, incident_number="INC-3", title="pm due",
                 severity=IncidentSeverity.SEV3, status=IncidentStatus.POSTMORTEM_DUE,
                 time_to_resolve_mins=45),
    ])
    await db.commit()

    r = await async_client.get("/api/v1/engineering/dashboard")
    assert r.status_code == 200, r.text
    dash = r.json()

    # Brute-force recount of the same session data with the pre-rewrite logic.
    services = (await db.execute(select(Service).where(Service.tenant_id == TENANT))).scalars().all()
    prs = (await db.execute(select(PullRequest).where(PullRequest.tenant_id == TENANT))).scalars().all()
    deploys = (await db.execute(select(Deployment).where(Deployment.tenant_id == TENANT))).scalars().all()
    incidents = (await db.execute(select(Incident).where(Incident.tenant_id == TENANT))).scalars().all()

    open_prs = [p for p in prs if _e(p.status) in ("OPEN", "IN_REVIEW", "CHANGES_REQUESTED")]
    failed = [d for d in deploys if _e(d.status) in ("FAILED", "ROLLED_BACK")]
    open_inc = [i for i in incidents if _e(i.status) not in ("RESOLVED", "CLOSED")]
    resolved = [i for i in incidents if i.time_to_resolve_mins is not None]

    assert dash["total_services"] == len(services)
    assert dash["unhealthy_services"] == len([s for s in services if _e(s.health) != "HEALTHY"])
    assert dash["open_pull_requests"] == len(open_prs)
    assert dash["prs_awaiting_review"] == len([p for p in open_prs if (p.approvals or 0) == 0])
    assert dash["deployments_total"] == len(deploys)
    assert dash["deployments_succeeded"] == len([d for d in deploys if _e(d.status) == "SUCCEEDED"])
    assert dash["change_failure_rate_pct"] == round(len(failed) / len(deploys) * 100, 1)
    assert dash["open_incidents"] == len(open_inc)
    assert dash["sev1_open"] == len([i for i in open_inc if _e(i.severity) == "SEV1"])
    assert dash["mttr_minutes"] == round(
        sum(i.time_to_resolve_mins for i in resolved) / len(resolved), 1)
    assert dash["postmortems_due"] == len([i for i in incidents if _e(i.status) == "POSTMORTEM_DUE"])
    # The NULL-approvals PR really is inside the awaiting count.
    assert dash["prs_awaiting_review"] == 1


@pytest.mark.asyncio
async def test_hr_dashboard_and_snapshot_match_python_recount(async_client: AsyncClient, db: AsyncSession):
    now = datetime.now(timezone.utc)
    db.add_all([
        HREmployee(tenant_id=TENANT, first_name="A", last_name="Active",
                   email="a.active@kaeos.io", status=EmploymentStatus.ACTIVE,
                   hire_date=date(2024, 1, 1), job_title="Engineer"),
        HREmployee(tenant_id=TENANT, first_name="T", last_name="Terminated",
                   email="t.term@kaeos.io", status=EmploymentStatus.TERMINATED,
                   hire_date=date(2023, 1, 1), job_title="Engineer",
                   termination_date=date(2025, 6, 30)),
        # The trap row: only termination_date set, status never flipped.
        # A plain GROUP BY on status would miss this one in turnover.
        HREmployee(tenant_id=TENANT, first_name="D", last_name="DateOnly",
                   email="d.dateonly@kaeos.io", status=EmploymentStatus.ACTIVE,
                   hire_date=date(2023, 1, 1), job_title="Engineer",
                   termination_date=date(2025, 12, 31)),
        HREmployee(tenant_id=TENANT, first_name="C", last_name="Contract",
                   email="c.contract@kaeos.io", status=EmploymentStatus.CONTRACTOR,
                   hire_date=date(2025, 1, 1), job_title="Consultant"),
    ])
    req = JobRequisition(tenant_id=TENANT, title="Backend Engineer", department="Engineering",
                         hiring_manager_id="mgr-1", job_description="Build APIs.",
                         status=ReqStatus.OPEN)
    filled_req = JobRequisition(tenant_id=TENANT, title="Old Role", department="Engineering",
                                hiring_manager_id="mgr-1", job_description="Done.",
                                status=ReqStatus.FILLED)
    db.add_all([req, filled_req])
    await db.commit()
    db.add_all([
        Candidate(tenant_id=TENANT, requisition_id=req.id, first_name="N", last_name="New",
                  email="n@example.com", stage=CandidateStage.APPLIED, applied_at=now),
        Candidate(tenant_id=TENANT, requisition_id=req.id, first_name="H", last_name="Hired",
                  email="h@example.com", stage=CandidateStage.HIRED,
                  applied_at=now - timedelta(days=70), updated_at=now - timedelta(days=40)),
        Candidate(tenant_id=TENANT, requisition_id=req.id, first_name="O", last_name="Offer",
                  email="o@example.com", stage=CandidateStage.OFFER_EXTENDED,
                  applied_at=now - timedelta(days=50)),
    ])
    db.add_all([
        FairnessAuditLog(tenant_id=TENANT, fairness_score=0.95, passed=True, rationale="ok"),
        FairnessAuditLog(tenant_id=TENANT, fairness_score=0.91, passed=True, rationale="ok"),
        FairnessAuditLog(tenant_id=TENANT, fairness_score=0.40, passed=False, rationale="flagged"),
    ])
    await db.commit()

    r = await async_client.get("/api/v1/hr/dashboard")
    assert r.status_code == 200, r.text
    dash = r.json()

    # Brute-force recount with the pre-rewrite logic.
    emps = (await db.execute(select(HREmployee).where(HREmployee.tenant_id == TENANT))).scalars().all()
    reqs = (await db.execute(select(JobRequisition).where(JobRequisition.tenant_id == TENANT))).scalars().all()
    cands = (await db.execute(select(Candidate).where(Candidate.tenant_id == TENANT))).scalars().all()
    logs = (await db.execute(select(FairnessAuditLog).where(FairnessAuditLog.tenant_id == TENANT))).scalars().all()

    terminated = [e for e in emps if _e(e.status) == "TERMINATED" or e.termination_date]
    hired = [c for c in cands if _e(c.stage) == "HIRED"]
    offers = [c for c in cands if _e(c.stage) == "OFFER_EXTENDED"]
    apps_this_month = [
        c for c in cands
        if c.applied_at and c.applied_at.year == now.year and c.applied_at.month == now.month
    ]

    assert len(terminated) == 2, "seed must include the termination_date-only employee"
    assert dash["total_employees"] == len(emps)
    assert dash["turnover_rate"] == round(len(terminated) / len(emps) * 100, 1)
    assert dash["open_positions"] == len([q for q in reqs if _e(q.status) == "OPEN"])
    assert dash["total_candidates"] == len(cands)
    assert dash["applications_this_month"] == len(apps_this_month)
    assert dash["offer_acceptance_rate"] == round(
        len(hired) / (len(hired) + len(offers)) * 100, 1)
    assert dash["compliance_score"] == round(
        sum(1 for log in logs if log.passed) / len(logs) * 100, 1)
    # Untouched no-data-source fields stay null.
    assert dash["avg_time_to_fill"] is None
    assert dash["satisfaction_score"] is None
    assert dash["training_completion"] is None

    # Snapshot endpoint: same SQL counts, time-to-fill diffed in Python.
    r = await async_client.post("/api/v1/hr/hr-metrics/snapshot")
    assert r.status_code == 201, r.text
    snap_id = r.json()["id"]
    rows = (await async_client.get("/api/v1/hr/hr-metrics")).json()
    snap = next(row for row in rows if row["id"] == snap_id)

    fill_days = [
        (c.updated_at - c.applied_at).days for c in hired
        if c.updated_at and c.applied_at and (c.updated_at - c.applied_at).days >= 0
    ]
    assert snap["total_headcount"] == len(emps)
    assert snap["active_contractors"] == len([e for e in emps if _e(e.status) == "CONTRACTOR"])
    assert snap["open_requisitions"] == len([q for q in reqs if _e(q.status) == "OPEN"])
    assert snap["offer_acceptance_rate"] == round(
        len(hired) / (len(hired) + len(offers)) * 100, 1)
    assert snap["time_to_fill_avg_days"] == round(sum(fill_days) / len(fill_days), 1)
