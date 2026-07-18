"""
KAEOS HR Vertical — Database Seed Script
Seeds the HR tables with realistic sample data so the frontend renders live data.
Run with: python -m app.hr.seed
"""
import asyncio
import uuid
from datetime import date, datetime, timedelta
import random

from app.core.database import async_engine, AsyncSessionLocal
from app.models.domain import Base
from app.hr.models.core import HREmployee, EmploymentStatus
from app.hr.models.recruiting import JobRequisition, Candidate, ReqStatus, CandidateStage
from app.hr.models.time_attendance import TimeOffRequest, LeaveType, LeaveStatus
from app.hr.models.performance import PerformanceReview, ReviewCycle

TENANT = "tenant_acme"  # demo tenant — matches seed_demo_user and dev-mode tenant

def _id():
    return str(uuid.uuid4())

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


async def seed():
    # Ensure tables exist
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as db:
        # ── 1. Seed Employees ──
        employees = []
        for i in range(20):
            emp = HREmployee(
                id=_id(),
                tenant_id=TENANT,
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
                id=_id(),
                tenant_id=TENANT,
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
        for first, last in cand_names:
            cand = Candidate(
                id=_id(),
                tenant_id=TENANT,
                requisition_id=random.choice(requisitions).id,
                first_name=first,
                last_name=last,
                email=f"{first.lower()}.{last.lower()}@gmail.com",
                stage=random.choice(stages),
                ai_score=round(random.uniform(25, 98), 1),
                ai_summary=f"{first} shows strong alignment with role requirements.",
            )
            db.add(cand)

        # ── 4. Seed Time-Off Requests ──
        for _ in range(12):
            emp = random.choice(employees)
            start = date.today() + timedelta(days=random.randint(-30, 60))
            days_off = random.randint(1, 10)
            tor = TimeOffRequest(
                id=_id(),
                tenant_id=TENANT,
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
            id=_id(),
            tenant_id=TENANT,
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
                id=_id(),
                tenant_id=TENANT,
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

        await db.commit()
        print("[SUCCESS] Seeded HR database:")
        print(f"   - {len(employees)} employees")
        print(f"   - {len(requisitions)} job requisitions")
        print(f"   - {len(cand_names)} candidates")
        print("   - 12 time-off requests")
        print("   - 14 performance reviews")
        print("   - 1 review cycle")


if __name__ == "__main__":
    asyncio.run(seed())
