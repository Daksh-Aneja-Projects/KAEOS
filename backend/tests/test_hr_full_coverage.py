"""
Coverage for the HR full-schema-depth pass: list/CRUD endpoints for the 9
previously-uncovered model groups (Benefits, Compensation, Onboarding/
Offboarding, Learning, Employee Relations, Workforce Planning, Payroll,
Compliance, Analytics) plus Interviews/EmployeeDocuments/Timesheets, the 6
previously-dead HR agent triggers, the PerformanceReview workflow, and the
BambooHR connector sync route.

Unit-level: SQLite in-memory via conftest's async_client/db fixtures (see
tests/conftest.py). Agent-trigger tests that go through the gated 7-gate
pipeline follow the exact no-provider-simulation pattern already established
in tests/test_hr_api_gated.py (monkeypatch provider_available + init_db +
skip under KAEOS_FAKE_LLM) so they run deterministically offline.
"""
import uuid
from datetime import date, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.hr.models.core import HREmployee, EmploymentStatus
from app.hr.models.recruiting import JobRequisition, Candidate, CandidateStage, ReqStatus
from app.services.llm_router import LLMRouter

TENANT = "tenant_acme"  # dev-mode default tenant (app/core/tenant.py:_DEV_TENANT)


async def _no_provider(self, *args, **kwargs) -> bool:
    """Forces the deterministic SIMULATED LLM path — see test_hr_api_gated.py."""
    return False


def _skip_if_fake_llm():
    import os
    if os.environ.get("KAEOS_FAKE_LLM"):
        pytest.skip("Uses its own no-provider simulation; incompatible with KAEOS_FAKE_LLM")


async def _mk_employee(db: AsyncSession, **overrides) -> HREmployee:
    defaults = dict(
        tenant_id=TENANT, first_name="Test", last_name="Employee",
        email=f"test.{uuid.uuid4().hex[:10]}@kaeos.io",
        status=EmploymentStatus.ACTIVE, hire_date=date(2024, 1, 1), job_title="Engineer",
    )
    defaults.update(overrides)
    emp = HREmployee(**defaults)
    db.add(emp)
    await db.commit()
    await db.refresh(emp)
    return emp


async def _mk_requisition_and_candidate(db: AsyncSession) -> Candidate:
    req = JobRequisition(
        tenant_id=TENANT, title="Backend Engineer", department="Engineering",
        hiring_manager_id="mgr-1", job_description="Build APIs.", status=ReqStatus.OPEN,
    )
    db.add(req)
    await db.commit()
    await db.refresh(req)
    cand = Candidate(
        tenant_id=TENANT, requisition_id=req.id, first_name="Ada", last_name="Lovelace",
        email=f"ada.{uuid.uuid4().hex[:8]}@example.com", stage=CandidateStage.APPLIED,
    )
    db.add(cand)
    await db.commit()
    await db.refresh(cand)
    return cand


# ── Benefits ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_benefit_plan_and_enrollment_crud(async_client: AsyncClient, db: AsyncSession):
    emp = await _mk_employee(db)

    r = await async_client.post("/api/v1/hr/benefit-plans", json={
        "name": "Test PPO Plan", "provider": "Anthem", "benefit_type": "HEALTH",
        "employee_cost_individual": 200.0, "employer_contribution": 500.0,
    })
    assert r.status_code == 201, r.text
    plan_id = r.json()["id"]

    r = await async_client.get("/api/v1/hr/benefit-plans")
    assert r.status_code == 200
    assert any(p["id"] == plan_id for p in r.json())

    r = await async_client.post("/api/v1/hr/benefit-enrollments", json={
        "employee_id": emp.id, "plan_id": plan_id, "coverage_level": "INDIVIDUAL",
        "effective_date": str(date.today()),
    })
    assert r.status_code == 201, r.text
    enrollment_id = r.json()["id"]
    assert r.json()["status"] == "PENDING"

    r = await async_client.get(f"/api/v1/hr/benefit-enrollments?employee_id={emp.id}")
    assert r.status_code == 200
    assert any(e["id"] == enrollment_id for e in r.json())

    # Unknown employee/plan is a 404, never a silent 500 or a fabricated row.
    r = await async_client.post("/api/v1/hr/benefit-enrollments", json={
        "employee_id": "no-such-employee", "plan_id": plan_id, "effective_date": str(date.today()),
    })
    assert r.status_code == 404

    r = await async_client.post(f"/api/v1/hr/benefit-enrollments/{enrollment_id}/transition",
                                json={"to_state": "ACTIVE"})
    assert r.status_code == 200, r.text
    assert r.json()["to_state"] == "ACTIVE"


@pytest.mark.asyncio
async def test_verify_benefit_enrollment_agent(async_client: AsyncClient, db: AsyncSession, monkeypatch):
    _skip_if_fake_llm()
    monkeypatch.setattr(LLMRouter, "provider_available", _no_provider)
    from app.core.database import init_db
    await init_db()

    emp = await _mk_employee(db)
    r = await async_client.post("/api/v1/hr/benefit-plans", json={
        "name": "Dental Plan", "provider": "Delta", "benefit_type": "DENTAL",
    })
    plan_id = r.json()["id"]
    r = await async_client.post("/api/v1/hr/benefit-enrollments", json={
        "employee_id": emp.id, "plan_id": plan_id, "effective_date": str(date.today()),
    })
    enrollment_id = r.json()["id"]

    r = await async_client.post(f"/api/v1/hr/benefit-enrollments/{enrollment_id}/verify")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "verified" in body and "status" in body


# ── Compensation ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_compensation_crud_and_supersession(async_client: AsyncClient, db: AsyncSession):
    emp = await _mk_employee(db)

    r = await async_client.post("/api/v1/hr/compensation", json={
        "employee_id": emp.id, "base_amount": 120000, "effective_date": "2024-01-01",
    })
    assert r.status_code == 201, r.text
    first_id = r.json()["id"]

    # A newer current record must supersede the prior one (is_current flips).
    r = await async_client.post("/api/v1/hr/compensation", json={
        "employee_id": emp.id, "base_amount": 135000, "effective_date": "2025-01-01",
        "change_reason": "Merit increase",
    })
    assert r.status_code == 201, r.text

    r = await async_client.get(f"/api/v1/hr/compensation?employee_id={emp.id}")
    rows = {row["id"]: row for row in r.json()}
    assert rows[first_id]["is_current"] is False


@pytest.mark.asyncio
async def test_compensation_market_analysis_agent(async_client: AsyncClient, db: AsyncSession, monkeypatch):
    _skip_if_fake_llm()
    monkeypatch.setattr(LLMRouter, "provider_available", _no_provider)

    emp = await _mk_employee(db)
    r = await async_client.post("/api/v1/hr/compensation", json={
        "employee_id": emp.id, "base_amount": 130000, "effective_date": str(date.today()),
    })
    comp_id = r.json()["id"]

    r = await async_client.post(f"/api/v1/hr/compensation/{comp_id}/market-analysis")
    assert r.status_code == 200, r.text
    assert "analysis" in r.json()

    # Never auto-writes pay: base_amount is unchanged by the agent.
    r = await async_client.get(f"/api/v1/hr/compensation?employee_id={emp.id}")
    assert r.json()[0]["base_amount"] == 130000


# ── Onboarding / Offboarding ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_boarding_plan_and_task_workflow(async_client: AsyncClient, db: AsyncSession):
    emp = await _mk_employee(db, status=EmploymentStatus.ONBOARDING)

    r = await async_client.post("/api/v1/hr/boarding-plans", json={
        "employee_id": emp.id, "plan_type": "ONBOARDING",
        "start_date": str(date.today()), "tasks": ["Provision laptop", "Sign handbook"],
    })
    assert r.status_code == 201, r.text
    assert r.json()["total_tasks"] == 2

    r = await async_client.get(f"/api/v1/hr/boarding-plans?employee_id={emp.id}")
    plan = r.json()[0]
    assert plan["completed_tasks"] == 0

    r = await async_client.get(f"/api/v1/hr/boarding-tasks?plan_id={plan['id']}")
    tasks = r.json()
    assert len(tasks) == 2
    task_id = tasks[0]["id"]

    r = await async_client.post(f"/api/v1/hr/boarding-tasks/{task_id}/transition",
                                json={"to_state": "IN_PROGRESS"})
    assert r.status_code == 200, r.text
    r = await async_client.post(f"/api/v1/hr/boarding-tasks/{task_id}/transition",
                                json={"to_state": "COMPLETED"})
    assert r.status_code == 200, r.text

    # The plan's progress counter is derived from the sibling tasks, not user-set.
    r = await async_client.get(f"/api/v1/hr/boarding-plans?employee_id={emp.id}")
    assert r.json()[0]["completed_tasks"] == 1


@pytest.mark.asyncio
async def test_onboarding_checkin_agent(async_client: AsyncClient, db: AsyncSession, monkeypatch):
    _skip_if_fake_llm()
    monkeypatch.setattr(LLMRouter, "provider_available", _no_provider)
    from app.core.database import init_db
    await init_db()

    emp = await _mk_employee(db, status=EmploymentStatus.ONBOARDING)

    r = await async_client.post(f"/api/v1/hr/employees/{emp.id}/onboarding-checkin", json={
        "week_num": 2, "response": "Things are going well so far.",
    })
    assert r.status_code == 200, r.text
    assert r.json()["week_num"] == 2

    # No response -> NO_RESPONSE, never a fabricated sentiment score.
    r = await async_client.post(f"/api/v1/hr/employees/{emp.id}/onboarding-checkin", json={"week_num": 1})
    assert r.status_code == 200
    assert r.json()["status"] == "NO_RESPONSE"
    assert r.json()["sentiment_score"] is None


@pytest.mark.asyncio
async def test_offboarding_exit_interview_agent(async_client: AsyncClient, db: AsyncSession, monkeypatch):
    _skip_if_fake_llm()
    monkeypatch.setattr(LLMRouter, "provider_available", _no_provider)

    emp = await _mk_employee(db, status=EmploymentStatus.TERMINATED, termination_date=date.today())

    r = await async_client.post(f"/api/v1/hr/employees/{emp.id}/offboarding-exit-interview", json={
        "survey_responses": {"reason_for_leaving": "New opportunity", "would_recommend": "Yes"},
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["boarding_plan_id"] and body["task_id"]

    # Persisted onto a real BoardingTask (Exit Interview), not just returned and forgotten.
    r = await async_client.get(f"/api/v1/hr/boarding-tasks?plan_id={body['boarding_plan_id']}")
    tasks = r.json()
    assert any(t["title"] == "Exit Interview" and t["status"] == "COMPLETED" for t in tasks)
    assert any(t["automation_result"] for t in tasks)


# ── Learning ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_course_and_enrollment_workflow(async_client: AsyncClient, db: AsyncSession):
    emp = await _mk_employee(db)

    r = await async_client.post("/api/v1/hr/courses", json={"title": "Security Awareness"})
    assert r.status_code == 201, r.text
    course_id = r.json()["id"]

    r = await async_client.post("/api/v1/hr/course-enrollments", json={
        "employee_id": emp.id, "course_id": course_id,
    })
    assert r.status_code == 201, r.text
    enrollment_id = r.json()["id"]

    r = await async_client.post(f"/api/v1/hr/course-enrollments/{enrollment_id}/transition",
                                json={"to_state": "IN_PROGRESS"})
    assert r.status_code == 200, r.text
    r = await async_client.post(f"/api/v1/hr/course-enrollments/{enrollment_id}/transition",
                                json={"to_state": "COMPLETED"})
    assert r.status_code == 200, r.text

    r = await async_client.get(f"/api/v1/hr/course-enrollments?employee_id={emp.id}")
    row = r.json()[0]
    assert row["status"] == "COMPLETED"
    assert row["progress_pct"] == 100.0
    assert row["completed_at"] is not None


# ── Employee Relations ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_er_case_workflow(async_client: AsyncClient, db: AsyncSession):
    reporter = await _mk_employee(db)
    accused = await _mk_employee(db)

    r = await async_client.post("/api/v1/hr/er-cases", json={
        "title": "Test complaint", "description": "A workplace conduct concern was raised.",
        "reporter_id": reporter.id, "accused_id": accused.id, "category": "POLICY_VIOLATION",
    })
    assert r.status_code == 201, r.text
    case_id = r.json()["id"]
    assert r.json()["status"] == "OPEN"

    r = await async_client.post(f"/api/v1/hr/er-cases/{case_id}/transition",
                                json={"to_state": "UNDER_INVESTIGATION"})
    assert r.status_code == 200, r.text
    r = await async_client.post(f"/api/v1/hr/er-cases/{case_id}/transition",
                                json={"to_state": "RESOLVED"})
    assert r.status_code == 200, r.text
    r = await async_client.post(f"/api/v1/hr/er-cases/{case_id}/transition",
                                json={"to_state": "CLOSED"})
    assert r.status_code == 200, r.text

    r = await async_client.get("/api/v1/hr/er-cases")
    row = next(c for c in r.json() if c["id"] == case_id)
    assert row["status"] == "CLOSED"


@pytest.mark.asyncio
async def test_er_case_triage_agent(async_client: AsyncClient, db: AsyncSession, monkeypatch):
    _skip_if_fake_llm()
    monkeypatch.setattr(LLMRouter, "provider_available", _no_provider)
    from app.core.database import init_db
    await init_db()

    reporter = await _mk_employee(db)
    r = await async_client.post("/api/v1/hr/er-cases", json={
        "title": "Test complaint", "description": "A workplace conduct concern was raised.",
        "reporter_id": reporter.id, "category": "HARASSMENT",
    })
    case_id = r.json()["id"]

    r = await async_client.post(f"/api/v1/hr/er-cases/{case_id}/triage")
    assert r.status_code == 200, r.text
    assert "case_id" in r.json()


# ── Workforce Planning ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_headcount_plan_workflow(async_client: AsyncClient):
    r = await async_client.post("/api/v1/hr/headcount-plans", json={
        "name": "FY26 Test Scaling Plan", "target_year": 2026, "budget_allocated": 500000,
        "planned_positions": [{"title": "Engineer", "count": 2}],
    })
    assert r.status_code == 201, r.text
    plan_id = r.json()["id"]
    assert r.json()["status"] == "DRAFT"

    r = await async_client.post(f"/api/v1/hr/headcount-plans/{plan_id}/transition",
                                json={"to_state": "ACTIVE"})
    assert r.status_code == 200, r.text

    r = await async_client.get("/api/v1/hr/headcount-plans")
    assert any(p["id"] == plan_id for p in r.json())


# ── Payroll ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_payroll_run_and_payslip_generation(async_client: AsyncClient, db: AsyncSession):
    emp1 = await _mk_employee(db)
    _emp2 = await _mk_employee(db)
    await async_client.post("/api/v1/hr/compensation", json={
        "employee_id": emp1.id, "base_amount": 100000, "effective_date": "2024-01-01",
    })
    # emp2 deliberately has NO compensation record - must be skipped, not fabricated.

    r = await async_client.post("/api/v1/hr/payroll-runs", json={
        "period_start": "2026-01-01", "period_end": "2026-01-15", "pay_date": "2026-01-20",
    })
    assert r.status_code == 201, r.text
    run_id = r.json()["id"]

    r = await async_client.post(f"/api/v1/hr/payroll-runs/{run_id}/generate-payslips")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["created"] == 1
    assert body["skipped_no_compensation"] >= 1

    # Idempotent: running it again creates nothing new for the same employees.
    r = await async_client.post(f"/api/v1/hr/payroll-runs/{run_id}/generate-payslips")
    assert r.json()["created"] == 0
    assert r.json()["skipped_existing"] >= 1

    r = await async_client.get(f"/api/v1/hr/payslips?run_id={run_id}")
    assert len(r.json()) == 1
    payslip = r.json()[0]
    assert payslip["employee_id"] == emp1.id
    assert payslip["gross_pay"] > 0
    # No tax-withholding engine: net equals gross rather than a guessed number.
    assert payslip["net_pay"] == payslip["gross_pay"]

    r = await async_client.post(f"/api/v1/hr/payroll-runs/{run_id}/transition", json={"to_state": "PROCESSING"})
    assert r.status_code == 200, r.text


# ── Compliance ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_compliance_report_and_violation(async_client: AsyncClient):
    r = await async_client.post("/api/v1/hr/compliance-reports", json={
        "framework": "OSHA", "report_name": "Test OSHA log", "period_year": 2026,
    })
    assert r.status_code == 201, r.text
    report_id = r.json()["id"]

    r = await async_client.get("/api/v1/hr/compliance-reports")
    assert any(rep["id"] == report_id for rep in r.json())


@pytest.mark.asyncio
async def test_eeoc_compliance_report_generation(async_client: AsyncClient, db: AsyncSession):
    # Insufficient cohort data -> a real (not fabricated) "passed" result with 0 decided.
    r = await async_client.post("/api/v1/hr/compliance-reports/eeoc/generate")
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["decided_total"] == 0
    assert body["passed"] is True

    r = await async_client.get("/api/v1/hr/compliance-violations")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_compliance_violation_resolve(async_client: AsyncClient, db: AsyncSession):
    from app.hr.models.compliance import ComplianceViolation
    v = ComplianceViolation(tenant_id=TENANT, framework="I9", severity="WARNING",
                            description="Test violation for resolve endpoint.")
    db.add(v)
    await db.commit()
    await db.refresh(v)

    r = await async_client.post(f"/api/v1/hr/compliance-violations/{v.id}/resolve",
                                json={"resolution_notes": "Reviewed and corrected."})
    assert r.status_code == 200, r.text
    assert r.json()["resolved"] is True

    r = await async_client.get("/api/v1/hr/compliance-violations?resolved=true")
    assert any(row["id"] == v.id for row in r.json())


# ── HR Metric Snapshots ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_hr_metric_snapshot_generation_and_upsert(async_client: AsyncClient, db: AsyncSession):
    _emp = await _mk_employee(db)

    r = await async_client.post("/api/v1/hr/hr-metrics/snapshot")
    assert r.status_code == 201, r.text
    first_id = r.json()["id"]
    assert r.json()["total_headcount"] == 1

    # Running again the same day upserts (does not duplicate) today's snapshot.
    await _mk_employee(db)
    r = await async_client.post("/api/v1/hr/hr-metrics/snapshot")
    assert r.json()["id"] == first_id
    assert r.json()["total_headcount"] == 2

    r = await async_client.get("/api/v1/hr/hr-metrics")
    assert len(r.json()) == 1


# ── Interviews ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_interview_schedule_and_feedback(async_client: AsyncClient, db: AsyncSession):
    interviewer = await _mk_employee(db, job_title="Engineering Manager")
    cand = await _mk_requisition_and_candidate(db)

    r = await async_client.post("/api/v1/hr/interviews", json={
        "candidate_id": cand.id, "interviewer_id": interviewer.id,
        "scheduled_at": datetime.now().isoformat(), "interview_type": "Technical",
    })
    assert r.status_code == 201, r.text
    interview_id = r.json()["id"]

    r = await async_client.get(f"/api/v1/hr/interviews?candidate_id={cand.id}")
    assert any(i["id"] == interview_id for i in r.json())

    r = await async_client.post(f"/api/v1/hr/interviews/{interview_id}/feedback", json={
        "score": 4, "recommendation": "HIRE", "notes": "Strong technical fundamentals.",
    })
    assert r.status_code == 200, r.text
    assert r.json()["feedback_submitted"] is True


# ── Employee Documents ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_employee_document_upload_and_sign(async_client: AsyncClient, db: AsyncSession):
    emp = await _mk_employee(db)

    r = await async_client.post("/api/v1/hr/employee-documents", json={
        "employee_id": emp.id, "doc_type": "OFFER_LETTER", "title": "Offer Letter",
        "file_path": "documents/offer.pdf",
    })
    assert r.status_code == 201, r.text
    doc_id = r.json()["id"]

    r = await async_client.get(f"/api/v1/hr/employee-documents?employee_id={emp.id}")
    row = next(d for d in r.json() if d["id"] == doc_id)
    assert row["is_signed"] is False

    r = await async_client.post(f"/api/v1/hr/employee-documents/{doc_id}/sign")
    assert r.status_code == 200, r.text
    assert r.json()["is_signed"] is True


# ── Timesheets ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_timesheet_crud_and_transition(async_client: AsyncClient, db: AsyncSession):
    emp = await _mk_employee(db)

    r = await async_client.post("/api/v1/hr/timesheets", json={
        "employee_id": emp.id, "period_start": "2026-01-05", "period_end": "2026-01-11",
        "total_regular_hours": 40,
    })
    assert r.status_code == 201, r.text
    ts_id = r.json()["id"]
    assert r.json()["status"] == "DRAFT"

    r = await async_client.post(f"/api/v1/hr/timesheets/{ts_id}/transition", json={"to_state": "SUBMITTED"})
    assert r.status_code == 200, r.text
    r = await async_client.post(f"/api/v1/hr/timesheets/{ts_id}/transition", json={"to_state": "APPROVED"})
    assert r.status_code == 200, r.text


# ── Performance Reviews ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_performance_review_full_lifecycle(async_client: AsyncClient, db: AsyncSession):
    emp = await _mk_employee(db)
    reviewer = await _mk_employee(db, job_title="Engineering Manager")

    r = await async_client.post("/api/v1/hr/performance-cycles", json={
        "name": "Test Cycle", "start_date": "2026-01-01T00:00:00", "end_date": "2026-06-30T00:00:00",
    })
    assert r.status_code == 201, r.text
    cycle_id = r.json()["id"]

    r = await async_client.post("/api/v1/hr/performance-reviews", json={
        "cycle_id": cycle_id, "employee_id": emp.id, "reviewer_id": reviewer.id,
    })
    assert r.status_code == 201, r.text
    review_id = r.json()["id"]
    assert r.json()["status"] == "DRAFT"

    r = await async_client.post(f"/api/v1/hr/performance-reviews/{review_id}/transition",
                                json={"to_state": "PENDING_EMPLOYEE"})
    assert r.status_code == 200, r.text

    # Manager rating cannot skip ahead of the self-rating.
    r = await async_client.post(f"/api/v1/hr/performance-reviews/{review_id}/manager-rating",
                                json={"rating": 4, "assessment": "Solid quarter."})
    assert r.status_code == 409

    r = await async_client.post(f"/api/v1/hr/performance-reviews/{review_id}/self-rating",
                                json={"rating": 4, "assessment": "I met my goals this quarter."})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "PENDING_MANAGER"

    r = await async_client.post(f"/api/v1/hr/performance-reviews/{review_id}/manager-rating",
                                json={"rating": 5, "assessment": "Exceeded expectations."})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "COMPLETED"

    r = await async_client.get("/api/v1/hr/performance-reviews")
    row = next(rv for rv in r.json() if rv["id"] == review_id)
    assert row["status"] == "COMPLETED"
    assert row["manager_rating"] == 5


@pytest.mark.asyncio
async def test_performance_synthesize_feedback_agent(async_client: AsyncClient, db: AsyncSession, monkeypatch):
    _skip_if_fake_llm()
    monkeypatch.setattr(LLMRouter, "provider_available", _no_provider)

    emp = await _mk_employee(db)
    reviewer = await _mk_employee(db, job_title="Engineering Manager")
    r = await async_client.post("/api/v1/hr/performance-cycles", json={
        "name": "Test Cycle", "start_date": "2026-01-01T00:00:00", "end_date": "2026-06-30T00:00:00",
    })
    cycle_id = r.json()["id"]
    r = await async_client.post("/api/v1/hr/performance-reviews", json={
        "cycle_id": cycle_id, "employee_id": emp.id, "reviewer_id": reviewer.id,
    })
    review_id = r.json()["id"]

    r = await async_client.post(f"/api/v1/hr/performance-reviews/{review_id}/synthesize-feedback", json={
        "raw_feedback": ["Great collaborator.", "Could improve on documentation."],
    })
    assert r.status_code == 200, r.text
    assert "analysis" in r.json()


# ── Workflow specs surface every new entity type ────────────────────────────

@pytest.mark.asyncio
async def test_hr_workflows_include_new_entity_types(async_client: AsyncClient):
    r = await async_client.get("/api/v1/hr/workflows")
    assert r.status_code == 200
    specs = r.json()
    for entity_type in (
        "time_off_request", "job_requisition", "benefit_enrollment", "boarding_task",
        "er_case", "payroll_run", "course_enrollment", "headcount_plan", "timesheet",
        "performance_review",
    ):
        assert entity_type in specs, f"{entity_type} missing from GET /hr/workflows"


# ── BambooHR Connector ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_bamboohr_sync_bad_credentials_fails_closed(async_client: AsyncClient, monkeypatch):
    """Mocks a failed auth check (no real network in tests) and verifies the
    route fails closed with 502 rather than silently syncing nothing."""
    from app.hr.connectors import bamboohr as bamboohr_module

    async def _test_connection_fails(self):
        return False

    monkeypatch.setattr(bamboohr_module.BambooHRConnector, "test_connection", _test_connection_fails)

    r = await async_client.post("/api/v1/hr/connectors/bamboohr/sync", json={
        "subdomain": "no-such-subdomain-kaeos-test", "api_key": "fake-key",
    })
    assert r.status_code == 502


@pytest.mark.asyncio
async def test_bamboohr_sync_upserts_employees(async_client: AsyncClient, db: AsyncSession, monkeypatch):
    """Mocks the connector's HTTP calls (no real network) and verifies the
    upsert logic in app/hr/connectors/bamboohr.py:sync_employees end to end."""
    from app.hr.connectors import bamboohr as bamboohr_module

    async def _test_connection(self):
        return True

    async def _get_employees(self, status="all"):
        return [
            {"id": "bhr-1", "firstName": "New", "lastName": "Hire",
             "workEmail": f"new.hire.{uuid.uuid4().hex[:6]}@kaeos.io",
             "jobTitle": "Support Engineer", "location": "Remote"},
        ]

    monkeypatch.setattr(bamboohr_module.BambooHRConnector, "test_connection", _test_connection)
    monkeypatch.setattr(bamboohr_module.BambooHRConnector, "get_employees", _get_employees)

    r = await async_client.post("/api/v1/hr/connectors/bamboohr/sync", json={
        "subdomain": "acme", "api_key": "fake-key",
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["created"] == 1

    r = await async_client.get("/api/v1/hr/employees")
    assert any(e.get("job_title") == "Support Engineer" for e in r.json())

    # Re-running syncs the SAME worker_id -> updates, doesn't duplicate.
    r = await async_client.post("/api/v1/hr/connectors/bamboohr/sync", json={
        "subdomain": "acme", "api_key": "fake-key",
    })
    assert r.json()["created"] == 0
    assert r.json()["updated"] == 1
