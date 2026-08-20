"""
KAEOS HR Vertical — Database Seed Script
Seeds the HR tables with realistic sample data so the frontend renders live data.
Run with: python -m app.hr.seed
"""
import asyncio
import logging
from datetime import date, datetime, timedelta
from decimal import Decimal
import random


from app.core.database import async_engine, AsyncSessionLocal
from app.core.domain_seed import SEED_TENANT as TENANT, already_seeded, new_id, run_standalone
from app.hr.models.core import HREmployee, EmploymentStatus, EmployeeDocument, DocumentType
from app.hr.models.recruiting import JobRequisition, Candidate, ReqStatus, CandidateStage, Interview
from app.hr.models.time_attendance import TimeOffRequest, LeaveType, LeaveStatus, Timesheet
from app.hr.models.performance import PerformanceReview, ReviewCycle
from app.hr.models.benefits import BenefitPlan, BenefitEnrollment, BenefitType, EnrollmentStatus as BenefitEnrollStatus
from app.hr.models.compensation import Compensation, CompType
from app.hr.models.onboarding import BoardingPlan, BoardingTask, BoardingType, TaskStatus
from app.hr.models.learning import Course, CourseEnrollment, EnrollmentStatus as CourseEnrollStatus
from app.hr.models.employee_relations import ERCase, CaseStatus, CaseSeverity
from app.hr.models.workforce_planning import HeadcountPlan, PlanStatus
from app.hr.models.payroll import PayrollRun, Payslip, PayrollRunStatus
from app.hr.models.compliance import ComplianceReport, ComplianceViolation, ComplianceFramework
from app.hr.models.analytics import HRMetricSnapshot

logger = logging.getLogger(__name__)


FIRST_NAMES = ["Priya", "Arjun", "Maya", "Liam", "Sofia", "Ethan", "Zara", "Noah", "Aisha", "James",
               "Ananya", "Rohan", "Elena", "Marcus", "Yuki", "Oliver", "Fatima", "David", "Mei", "Alex"]
LAST_NAMES = ["Sharma", "Patel", "Rodriguez", "O'Brien", "Kim", "Nakamura", "Johnson", "Al-Rashid",
              "Chen", "Okafor", "Müller", "Singh", "Garcia", "Tanaka", "Williams", "Ahmed", "Brown",
              "Gupta", "Park", "Taylor"]
TITLES = ["Software Engineer", "Senior Engineer", "Staff Engineer", "Engineering Manager",
          "Product Manager", "UX Designer", "Data Scientist", "DevOps Engineer",
          "QA Lead", "Frontend Developer", "Backend Developer", "ML Engineer",
          "Technical Writer", "Security Engineer", "Platform Engineer", "SRE",
          "VP Engineering", "CTO", "Head of Design", "Product Analyst"]
LOCATIONS = ["San Francisco, CA", "New York, NY", "London, UK", "Bangalore, IN",
             "Toronto, CA", "Berlin, DE", "Singapore", "Remote", "Austin, TX", "Seattle, WA"]
DEPARTMENTS = ["Engineering", "Product", "Design", "Data Science", "Platform", "Security", "QA", "DevOps"]


async def seed_tenant(db, tenant: str) -> bool:
    # domain_seed.py already gates this whole module on HREmployee count == 0
    # for the tenant, but it is also runnable directly (`python -m app.hr.seed`)
    # - guard here too so a second run never duplicates the whole HR schema's
    # worth of demo rows.
    if await already_seeded(db, "HR", HREmployee, tenant):
        return False

    # ── 1. Seed Employees ──
    employees = []
    for i in range(20):
        emp = HREmployee(
            id=new_id(),
            tenant_id=tenant,
            first_name=FIRST_NAMES[i],
            last_name=LAST_NAMES[i],
            email=f"{FIRST_NAMES[i].lower()}.{LAST_NAMES[i].lower()}@kaeos.io",
            phone=f"+1-555-{random.randint(1000, 9999)}",
            status=random.choice([EmploymentStatus.ACTIVE] * 15 + [EmploymentStatus.ONBOARDING] * 3 + [EmploymentStatus.LEAVE] * 2),
            hire_date=date(2023, 1, 1) + timedelta(days=random.randint(0, 900)),
            job_title=TITLES[i],
            location=random.choice(LOCATIONS),
            is_remote=random.choice([True, False]),
            cost_center=f"CC-{random.randint(100, 999)}",
        )
        employees.append(emp)
        db.add(emp)

    await db.flush()  # Get IDs assigned

    # ── 2. Seed Job Requisitions ──
    req_titles = [
        "Senior Backend Engineer", "Staff ML Engineer", "Product Designer",
        "Engineering Manager - Platform", "DevOps Lead", "Data Analyst",
        "Security Engineer II", "Frontend Architect"
    ]
    requisitions = []
    for i, title in enumerate(req_titles):
        req = JobRequisition(
            id=new_id(),
            tenant_id=tenant,
            title=title,
            department=random.choice(DEPARTMENTS),
            hiring_manager_id=employees[random.randint(0, 5)].id,
            status=random.choice([ReqStatus.OPEN] * 5 + [ReqStatus.FILLED] * 2 + [ReqStatus.DRAFT]),
            headcount=random.randint(1, 3),
            target_salary_min=random.choice([120000, 140000, 160000, 180000]),
            target_salary_max=random.choice([180000, 200000, 220000, 250000]),
            job_description=f"We are looking for a {title} to join our growing team.",
            ai_screening_enabled=True,
        )
        requisitions.append(req)
        db.add(req)

    await db.flush()

    # ── 3. Seed Candidates ──
    cand_names = [
        ("Jordan", "Lee"), ("Amara", "Osei"), ("Kai", "Taniguchi"),
        ("Isabella", "Rossi"), ("Dmitri", "Volkov"), ("Sana", "Mirza"),
        ("Lucas", "Bergström"), ("Nkechi", "Eze"), ("Harper", "Flynn"),
        ("Ravi", "Krishnan"), ("Chloe", "Dupont"), ("Omar", "Hassan"),
        ("Ingrid", "Svensson"), ("Javier", "Morales"), ("Anya", "Petrov"),
    ]
    stages = [CandidateStage.APPLIED, CandidateStage.AI_SCREENING,
              CandidateStage.RECRUITER_SCREEN, CandidateStage.HM_INTERVIEW,
              CandidateStage.PANEL_INTERVIEW, CandidateStage.OFFER_EXTENDED,
              CandidateStage.HIRED, CandidateStage.REJECTED]
    # Voluntary self-ID (EEOC) — isolated on the candidate, only ever read to
    # build cohort selection rates for the disparate-impact sweep, and nulled
    # on erasure. Never used in screening.
    _GENDERS = ["female", "male", "nonbinary"]
    _ETHNICITIES = ["asian", "black", "hispanic", "white", "two_or_more"]
    _AGE_BANDS = ["under_40", "40_plus"]
    candidates = []
    for first, last in cand_names:
        cand = Candidate(
            id=new_id(),
            tenant_id=tenant,
            requisition_id=random.choice(requisitions).id,
            first_name=first,
            last_name=last,
            email=f"{first.lower()}.{last.lower()}@gmail.com",
            stage=random.choice(stages),
            ai_score=round(random.uniform(25, 98), 1),
            ai_summary=f"{first} shows strong alignment with role requirements.",
            eeoc_data={
                "gender": random.choice(_GENDERS),
                "ethnicity": random.choice(_ETHNICITIES),
                "age_band": random.choice(_AGE_BANDS),
            },
        )
        candidates.append(cand)
        db.add(cand)

    await db.flush()  # candidates need ids before Interview rows reference them

    # ── 4. Seed Time-Off Requests ──
    for _ in range(12):
        emp = random.choice(employees)
        start = date.today() + timedelta(days=random.randint(-30, 60))
        days_off = random.randint(1, 10)
        tor = TimeOffRequest(
            id=new_id(),
            tenant_id=tenant,
            employee_id=emp.id,
            approver_id=employees[0].id,
            leave_type=random.choice(list(LeaveType)),
            status=random.choice([LeaveStatus.REQUESTED] * 4 + [LeaveStatus.APPROVED] * 6 + [LeaveStatus.DENIED] * 2),
            start_date=start,
            end_date=start + timedelta(days=days_off),
            hours_requested=days_off * 8.0,
        )
        db.add(tor)

    # ── 5. Seed Performance Reviews ──
    cycle = ReviewCycle(
        id=new_id(),
        tenant_id=tenant,
        name="H1 2026 Review Cycle",
        start_date=datetime(2026, 1, 1),
        end_date=datetime(2026, 6, 30),
        is_active=True,
    )
    db.add(cycle)
    await db.flush()

    review_statuses = ["DRAFT", "PENDING_EMPLOYEE", "PENDING_MANAGER", "COMPLETED"]
    for emp in employees[:14]:  # Reviews for 14 employees
        reviewer = random.choice([e for e in employees if e.id != emp.id])
        status = random.choice(review_statuses)
        rev = PerformanceReview(
            id=new_id(),
            tenant_id=tenant,
            cycle_id=cycle.id,
            employee_id=emp.id,
            reviewer_id=reviewer.id,
            self_rating=random.randint(3, 5) if status in ("PENDING_MANAGER", "COMPLETED") else None,
            manager_rating=random.randint(2, 5) if status == "COMPLETED" else None,
            self_assessment="Strong quarter with significant contributions." if status in ("PENDING_MANAGER", "COMPLETED") else None,
            manager_assessment="Exceeded expectations in key deliverables." if status == "COMPLETED" else None,
            ai_feedback_summary="Consistently high-performing contributor with growth potential in leadership." if status == "COMPLETED" else None,
            ai_growth_areas=["Leadership", "System Design"] if status == "COMPLETED" else [],
            status=status,
        )
        db.add(rev)

    # ── 6. Seed Benefit Plans + Enrollments ──
    benefit_plans_data = [
        ("Premium PPO Health Plan", "Anthem Blue Cross", BenefitType.HEALTH, 350.0, 850.0, 600.0),
        ("Standard Dental Plan", "Delta Dental", BenefitType.DENTAL, 25.0, 65.0, 40.0),
        ("Vision Care Plan", "VSP", BenefitType.VISION, 8.0, 20.0, 12.0),
        ("Basic Life Insurance", "MetLife", BenefitType.LIFE_INSURANCE, 0.0, 0.0, 50000.0),
        ("401(k) Retirement Plan", "Fidelity", BenefitType.RETIREMENT, 0.0, 0.0, 0.0),
        ("Flexible Spending Account", "WEX", BenefitType.FSA_HSA, 0.0, 0.0, 0.0),
    ]
    benefit_plans = []
    for name, provider, btype, cost_ind, cost_fam, employer_contrib in benefit_plans_data:
        plan = BenefitPlan(
            id=new_id(), tenant_id=tenant, name=name, provider=provider, benefit_type=btype,
            description=f"{name}, provided through {provider}.",
            employee_cost_individual=cost_ind, employee_cost_family=cost_fam,
            employer_contribution=employer_contrib,
        )
        benefit_plans.append(plan)
        db.add(plan)
    await db.flush()

    for emp in employees[:16]:
        for plan in random.sample(benefit_plans, k=random.randint(1, 3)):
            db.add(BenefitEnrollment(
                id=new_id(), tenant_id=tenant, employee_id=emp.id, plan_id=plan.id,
                status=random.choice([BenefitEnrollStatus.ACTIVE] * 6 + [BenefitEnrollStatus.PENDING] * 2
                                      + [BenefitEnrollStatus.WAIVED]),
                coverage_level=random.choice(["INDIVIDUAL", "INDIVIDUAL_PLUS_ONE", "FAMILY"]),
                effective_date=emp.hire_date,
                agent_verified=random.choice([True, True, False]),
            ))

    # ── 7. Seed Compensation (one current record per employee) ──
    SALARY_BY_TITLE = {
        "Software Engineer": 125000, "Senior Engineer": 155000, "Staff Engineer": 185000,
        "Engineering Manager": 175000, "Product Manager": 145000, "UX Designer": 115000,
        "Data Scientist": 150000, "DevOps Engineer": 135000, "QA Lead": 120000,
        "Frontend Developer": 118000, "Backend Developer": 128000, "ML Engineer": 165000,
        "Technical Writer": 95000, "Security Engineer": 155000, "Platform Engineer": 140000,
        "SRE": 145000, "VP Engineering": 260000, "CTO": 320000, "Head of Design": 210000,
        "Product Analyst": 110000,
    }
    comp_by_emp = {}
    for emp in employees:
        base = round(SALARY_BY_TITLE.get(emp.job_title, 120000) * random.uniform(0.92, 1.12), -2)
        comp = Compensation(
            id=new_id(), tenant_id=tenant, employee_id=emp.id, comp_type=CompType.SALARY,
            base_amount=base, currency="USD",
            target_bonus_pct=random.choice([0.0, 5.0, 10.0, 15.0, 20.0]),
            equity_grant=random.choice([0, 0, 2000, 5000, 10000]),
            equity_type=random.choice([None, "RSU", "ISO"]),
            vesting_schedule="4yr vest, 1yr cliff" if random.random() > 0.4 else None,
            effective_date=emp.hire_date, is_current=True,
            change_reason="New hire compensation",
        )
        comp_by_emp[emp.id] = comp
        db.add(comp)

    # ── 8. Terminate a couple of employees + seed Onboarding/Offboarding plans ──
    offboarding_emps = [e for e in employees if e.status == EmploymentStatus.ACTIVE][-2:]
    for e in offboarding_emps:
        e.status = EmploymentStatus.TERMINATED
        e.termination_date = date.today() - timedelta(days=random.randint(3, 20))
        db.add(e)

    onboarding_emps = [e for e in employees if e.status == EmploymentStatus.ONBOARDING]

    ONBOARDING_TASKS = [
        "Complete I-9 and W-4 paperwork", "Provision laptop and system accounts",
        "Complete employee handbook acknowledgment", "30-60-90 plan with manager",
        "Benefits enrollment",
    ]
    OFFBOARDING_TASKS = [
        "Revoke system access", "Return company equipment",
        "Final paycheck and COBRA notice", "Exit interview",
    ]

    for emp in onboarding_emps:
        start = datetime.combine(emp.hire_date, datetime.min.time())
        plan = BoardingPlan(
            id=new_id(), tenant_id=tenant, employee_id=emp.id, plan_type=BoardingType.ONBOARDING,
            status="ACTIVE", total_tasks=len(ONBOARDING_TASKS), completed_tasks=2,
            start_date=start, target_completion_date=start + timedelta(days=90),
        )
        db.add(plan)
        await db.flush()
        for i, title in enumerate(ONBOARDING_TASKS):
            status = TaskStatus.COMPLETED if i < 2 else TaskStatus.PENDING
            db.add(BoardingTask(
                id=new_id(), tenant_id=tenant, plan_id=plan.id, title=title,
                due_date=start + timedelta(days=(i + 1) * 7), status=status,
                completed_at=(start + timedelta(days=i)) if status == TaskStatus.COMPLETED else None,
                is_automated=(i == 1), automation_action="provision_accounts" if i == 1 else None,
            ))

    for emp in offboarding_emps:
        start = datetime.combine(emp.termination_date - timedelta(days=10), datetime.min.time())
        end = datetime.combine(emp.termination_date, datetime.min.time())
        plan = BoardingPlan(
            id=new_id(), tenant_id=tenant, employee_id=emp.id, plan_type=BoardingType.OFFBOARDING,
            status="ACTIVE", total_tasks=len(OFFBOARDING_TASKS), completed_tasks=1,
            start_date=start, target_completion_date=end,
        )
        db.add(plan)
        await db.flush()
        for i, title in enumerate(OFFBOARDING_TASKS):
            status = TaskStatus.COMPLETED if i == 0 else TaskStatus.PENDING
            db.add(BoardingTask(
                id=new_id(), tenant_id=tenant, plan_id=plan.id, title=title,
                due_date=start + timedelta(days=(i + 1) * 2), status=status,
                completed_at=start if status == TaskStatus.COMPLETED else None,
            ))

    # ── 9. Seed Courses + Course Enrollments ──
    courses_data = [
        ("Security Awareness Training", "Internal", True, 45),
        ("Anti-Harassment and Workplace Conduct", "Internal", True, 60),
        ("Data Privacy and GDPR Fundamentals", "Internal", True, 30),
        ("Leadership Essentials", "LinkedIn Learning", False, 120),
        ("Advanced System Design", "Internal", False, 180),
        ("Effective Communication", "Coursera", False, 90),
    ]
    courses = []
    for title, provider, compliance_req, minutes in courses_data:
        c = Course(
            id=new_id(), tenant_id=tenant, title=title, description=f"{title}, delivered via {provider}.",
            provider=provider, is_required_for_compliance=compliance_req, estimated_minutes=minutes,
        )
        courses.append(c)
        db.add(c)
    await db.flush()

    for emp in employees:
        for course in random.sample(courses, k=random.randint(1, 3)):
            status = random.choice([CourseEnrollStatus.COMPLETED] * 5 + [CourseEnrollStatus.IN_PROGRESS] * 3
                                    + [CourseEnrollStatus.ENROLLED] * 2)
            progress = (100.0 if status == CourseEnrollStatus.COMPLETED
                       else round(random.uniform(10, 90), 1) if status == CourseEnrollStatus.IN_PROGRESS else 0.0)
            db.add(CourseEnrollment(
                id=new_id(), tenant_id=tenant, employee_id=emp.id, course_id=course.id, status=status,
                progress_pct=progress, due_date=datetime.now() + timedelta(days=random.randint(-10, 60)),
                completed_at=(datetime.now() - timedelta(days=random.randint(1, 90)))
                             if status == CourseEnrollStatus.COMPLETED else None,
            ))

    # ── 10. Seed Employee Relations Cases ──
    er_case_data = [
        ("Workplace conduct complaint",
         "An employee raised a concern regarding a colleague's conduct in a team meeting.",
         "POLICY_VIOLATION", CaseSeverity.MEDIUM, CaseStatus.UNDER_INVESTIGATION),
        ("Compensation dispute",
         "An employee requested a review of their compensation relative to market benchmarks.",
         "DISPUTE", CaseSeverity.LOW, CaseStatus.RESOLVED),
        ("Anonymous harassment report",
         "An anonymous report was filed alleging inappropriate remarks in a project channel.",
         "HARASSMENT", CaseSeverity.HIGH, CaseStatus.OPEN),
    ]
    for title, desc, category, severity, status in er_case_data:
        reporter = random.choice(employees)
        accused = random.choice([e for e in employees if e.id != reporter.id])
        db.add(ERCase(
            id=new_id(), tenant_id=tenant, title=title, description=desc,
            reporter_id=reporter.id if random.random() > 0.3 else None,
            accused_id=accused.id,
            investigator_id=employees[0].id if status != CaseStatus.OPEN else None,
            category=category, severity=severity, status=status,
            ai_risk_assessment=("Moderate compliance risk; recommend HR review within 5 business days."
                                if status != CaseStatus.OPEN else None),
            ai_recommended_actions=(["Schedule interviews with involved parties",
                                     "Review relevant communication logs"] if status != CaseStatus.OPEN else []),
            opened_at=datetime.now() - timedelta(days=random.randint(5, 60)),
            closed_at=(datetime.now() - timedelta(days=random.randint(1, 4)))
                      if status in (CaseStatus.RESOLVED, CaseStatus.CLOSED) else None,
        ))

    # ── 11. Seed Headcount Plans ──
    headcount_plan_data = [
        ("FY26 Engineering Scaling", "Engineering", 2026, 2_400_000.0, PlanStatus.ACTIVE,
         [{"title": "Senior Backend Engineer", "count": 3, "target_qtr": "Q2", "est_salary": 155000},
          {"title": "Staff ML Engineer", "count": 1, "target_qtr": "Q3", "est_salary": 190000}]),
        ("FY26 Go-to-Market Expansion", "Sales", 2026, 900_000.0, PlanStatus.DRAFT,
         [{"title": "Account Executive", "count": 4, "target_qtr": "Q1", "est_salary": 110000}]),
    ]
    for name, dept, year, budget, status, positions in headcount_plan_data:
        db.add(HeadcountPlan(
            id=new_id(), tenant_id=tenant, name=name, department_id=dept, target_year=year,
            budget_allocated=budget, currency="USD", status=status, planned_positions=positions,
        ))

    # ── 12. Seed Payroll Runs + Payslips ──
    payroll_runs = []
    today = date.today()
    for months_back, run_status in [(2, PayrollRunStatus.COMPLETED), (1, PayrollRunStatus.COMPLETED),
                                    (0, PayrollRunStatus.PENDING_APPROVAL)]:
        start = (today.replace(day=1) - timedelta(days=months_back * 30)).replace(day=1)
        end = (start + timedelta(days=31)).replace(day=1) - timedelta(days=1)
        run = PayrollRun(
            id=new_id(), tenant_id=tenant, period_start=start, period_end=end, pay_date=end,
            status=run_status, ai_approved=(run_status == PayrollRunStatus.COMPLETED),
        )
        payroll_runs.append(run)
        db.add(run)
    await db.flush()

    for run in payroll_runs:
        period_days = (run.period_end - run.period_start).days + 1
        run_total_gross = Decimal("0")
        for emp in employees:
            if emp.status == EmploymentStatus.TERMINATED and emp.termination_date \
                    and emp.termination_date < run.period_start:
                continue
            comp = comp_by_emp.get(emp.id)
            if not comp:
                continue
            gross = round(comp.base_amount * Decimal(period_days) / Decimal(365), 2)
            run_total_gross += gross
            db.add(Payslip(id=new_id(), tenant_id=tenant, run_id=run.id, employee_id=emp.id,
                           gross_pay=gross, net_pay=gross))
        run.total_gross = round(run_total_gross, 2)
        run.total_net = round(run_total_gross, 2)
        db.add(run)

    # ── 13. Seed Compliance Reports + a Violation ──
    db.add(ComplianceReport(
        id=new_id(), tenant_id=tenant, framework=ComplianceFramework.EEOC,
        report_name="EEO-1 Component 1 Filing", period_year=2025, status="SUBMITTED",
        data={"total_employees": len(employees), "note": "Annual EEO-1 filing summary."},
        submitted_at=datetime.now() - timedelta(days=120),
    ))
    db.add(ComplianceReport(
        id=new_id(), tenant_id=tenant, framework=ComplianceFramework.OSHA,
        report_name="OSHA 300 Log Summary", period_year=2025, status="REVIEWED",
        data={"recordable_incidents": 0, "note": "No recordable workplace incidents in the reporting period."},
    ))
    db.add(ComplianceReport(
        id=new_id(), tenant_id=tenant, framework=ComplianceFramework.HIPAA,
        report_name="HIPAA Compliance Self-Assessment", period_year=2026, status="GENERATED",
        data={"phi_access_reviews_completed": True, "note": "Benefits administration PHI handling reviewed."},
    ))
    db.add(ComplianceViolation(
        id=new_id(), tenant_id=tenant, framework="I9", severity="WARNING",
        description="Section 2 of the I-9 was completed 1 business day past the 3-day statutory window "
                    "for one new hire.",
        context={"employee_id": (onboarding_emps[0].id if onboarding_emps else employees[0].id)},
        actor_id="hr_seed_demo_data", resolved=False,
    ))

    # ── 14. Seed HR Metric Snapshots (time-distributed, weekly) ──
    for weeks_back in range(8, 0, -1):
        snap_date = today - timedelta(weeks=weeks_back)
        db.add(HRMetricSnapshot(
            id=new_id(), tenant_id=tenant, snapshot_date=snap_date,
            total_headcount=max(len(employees) - max(0, weeks_back - 4), 10),
            active_contractors=sum(1 for e in employees if e.status == EmploymentStatus.CONTRACTOR),
            open_requisitions=sum(1 for r in requisitions if r.status == ReqStatus.OPEN),
            time_to_fill_avg_days=round(random.uniform(28, 45), 1),
            offer_acceptance_rate=round(random.uniform(65, 88), 1),
            total_payroll_run_rate=(round(sum(c.base_amount for c in comp_by_emp.values()) / 12, 2)
                                    if comp_by_emp else 0.0),
            diversity_metrics={},
        ))

    # ── 15. Seed Interviews (linked to candidates + employees) ──
    for cand in candidates[:8]:
        interviewer = random.choice(employees[:8])
        feedback_given = random.random() > 0.4
        db.add(Interview(
            id=new_id(), tenant_id=tenant, candidate_id=cand.id, interviewer_id=interviewer.id,
            scheduled_at=datetime.now() + timedelta(days=random.randint(-14, 20)),
            duration_mins=random.choice([30, 45, 60]),
            interview_type=random.choice(["Technical", "Behavioral", "System Design", "Hiring Manager"]),
            feedback_submitted=feedback_given,
            score=random.randint(2, 5) if feedback_given else None,
            recommendation=random.choice(["STRONG_HIRE", "HIRE", "NO_HIRE"]) if feedback_given else None,
            notes="Solid communication and problem-solving approach." if feedback_given else None,
        ))

    # ── 16. Seed Employee Documents ──
    DOC_TEMPLATES = [
        (DocumentType.I9, "Form I-9, Employment Eligibility Verification", True),
        (DocumentType.W4, "Form W-4, Employee Withholding Certificate", True),
        (DocumentType.OFFER_LETTER, "Signed Offer Letter", True),
        (DocumentType.HANDBOOK_ACK, "Employee Handbook Acknowledgment", True),
    ]
    for emp in employees:
        for doc_type, title, signed_default in DOC_TEMPLATES:
            signed = signed_default and random.random() > 0.1
            db.add(EmployeeDocument(
                id=new_id(), tenant_id=tenant, employee_id=emp.id, doc_type=doc_type, title=title,
                file_path=f"documents/{emp.id}/{doc_type.value.lower()}.pdf",
                is_signed=signed,
                signature_date=datetime.combine(emp.hire_date, datetime.min.time()) if signed else None,
                is_pii=True,
            ))

    # ── 17. Seed Timesheets ──
    for emp in employees:
        for weeks_back in range(1, 4):
            period_start = today - timedelta(days=today.weekday() + 7 * weeks_back)
            period_end = period_start + timedelta(days=6)
            ts_status = "PROCESSED" if weeks_back > 1 else random.choice(["SUBMITTED", "APPROVED"])
            db.add(Timesheet(
                id=new_id(), tenant_id=tenant, employee_id=emp.id,
                period_start=period_start, period_end=period_end,
                total_regular_hours=round(random.uniform(36, 40), 1),
                total_overtime_hours=round(random.uniform(0, 4), 1) if random.random() > 0.7 else 0.0,
                status=ts_status,
            ))

    await db.commit()
    logger.info("[SUCCESS] Seeded HR database:")
    logger.info(f"   - {len(employees)} employees")
    logger.info(f"   - {len(requisitions)} job requisitions")
    logger.info(f"   - {len(cand_names)} candidates")
    logger.info("   - 12 time-off requests")
    logger.info("   - 14 performance reviews")
    logger.info("   - 1 review cycle")
    logger.info(f"   - {len(benefit_plans_data)} benefit plans + enrollments")
    logger.info(f"   - {len(employees)} compensation records")
    logger.info(f"   - {len(onboarding_emps)} onboarding + {len(offboarding_emps)} offboarding plans")
    logger.info(f"   - {len(courses_data)} courses + enrollments")
    logger.info(f"   - {len(er_case_data)} ER cases")
    logger.info(f"   - {len(headcount_plan_data)} headcount plans")
    logger.info(f"   - {len(payroll_runs)} payroll runs + payslips")
    logger.info("   - 3 compliance reports + 1 violation")
    logger.info("   - 8 HR metric snapshots")
    logger.info("   - 8 interviews")
    logger.info(f"   - {len(employees) * len(DOC_TEMPLATES)} employee documents")
    logger.info(f"   - {len(employees) * 3} timesheets")
    return True


async def seed(tenant: str | None = None) -> bool:
    return await run_standalone(async_engine, AsyncSessionLocal, seed_tenant, tenant or TENANT)


if __name__ == "__main__":
    asyncio.run(seed())
