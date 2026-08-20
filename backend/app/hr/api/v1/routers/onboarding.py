"""KAEOS HR V1 — onboarding

Onboarding and offboarding: boarding plans, their tasks, the week-N
check-in and the exit-interview analysis.
"""
from datetime import datetime, timezone
from typing import List, Dict, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select, func as sqlfunc
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import record_security_event
from app.core.database import get_db
from app.core.department_endpoints import get_or_404
from app.core.tenant import approver_identity, get_tenant_id, require_role
from app.core.workflow import TransitionRequest, apply_transition
from app.hr.api.v1.routers._shared import _exec_id
from app.hr.models.core import HREmployee
from app.hr.models.onboarding import BoardingPlan, BoardingTask, BoardingType, TaskStatus
from app.hr.services.workflows import SPECS as WORKFLOW_SPECS

router = APIRouter()


# ── Onboarding & Offboarding (BoardingPlan / BoardingTask) ────────────────────

_DEFAULT_ONBOARDING_TASKS = [
    "Complete I-9 and W-4 paperwork", "Provision laptop and system accounts",
    "Complete employee handbook acknowledgment", "30-60-90 plan with manager",
    "Benefits enrollment",
]
_DEFAULT_OFFBOARDING_TASKS = [
    "Revoke system access", "Return company equipment",
    "Final paycheck and COBRA notice", "Exit Interview",
]


class BoardingPlanCreate(BaseModel):
    employee_id: str
    plan_type: str = Field("ONBOARDING", pattern="^(ONBOARDING|OFFBOARDING|CROSSBOARDING)$")
    start_date: datetime
    target_completion_date: Optional[datetime] = None
    tasks: List[str] = Field(default_factory=list)  # custom task titles; defaults used when empty


@router.get("/boarding-plans")
async def list_boarding_plans(
    employee_id: Optional[str] = None,
    tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db),
):
    stmt = select(BoardingPlan).where(BoardingPlan.tenant_id == tenant_id)
    if employee_id:
        stmt = stmt.where(BoardingPlan.employee_id == employee_id)
    rows = (await db.execute(stmt.order_by(BoardingPlan.start_date.desc()).limit(200))).scalars().all()
    return [{
        "id": p.id, "employee_id": p.employee_id,
        "plan_type": p.plan_type.value if hasattr(p.plan_type, "value") else str(p.plan_type),
        "status": p.status, "total_tasks": p.total_tasks, "completed_tasks": p.completed_tasks,
        "start_date": p.start_date.isoformat() if p.start_date else None,
        "target_completion_date": p.target_completion_date.isoformat() if p.target_completion_date else None,
    } for p in rows]


@router.post("/boarding-plans", status_code=201)
async def create_boarding_plan(
    body: BoardingPlanCreate, tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db),
):
    tenant_id = tenant["tenant_id"]
    await get_or_404(db, HREmployee, body.employee_id, tenant_id, detail="Employee not found")
    titles = body.tasks or (
        _DEFAULT_ONBOARDING_TASKS if body.plan_type == "ONBOARDING"
        else _DEFAULT_OFFBOARDING_TASKS if body.plan_type == "OFFBOARDING" else []
    )
    plan = BoardingPlan(
        tenant_id=tenant_id, employee_id=body.employee_id, plan_type=body.plan_type,
        start_date=body.start_date, target_completion_date=body.target_completion_date,
        total_tasks=len(titles), completed_tasks=0, status="ACTIVE",
    )
    db.add(plan)
    await db.flush()
    for title in titles:
        db.add(BoardingTask(
            tenant_id=tenant_id, plan_id=plan.id, title=title,
            due_date=body.target_completion_date or body.start_date, status=TaskStatus.PENDING,
        ))
    await db.commit()
    await db.refresh(plan)
    await record_security_event(tenant_id=tenant_id, event_type="MODIFICATION", action="WRITE",
        actor=approver_identity(tenant), actor_role=tenant.get("role"), resource_type="boarding_plan", resource_id=plan.id)
    return {"id": plan.id, "total_tasks": plan.total_tasks}


class BoardingTaskCreate(BaseModel):
    plan_id: str
    title: str
    description: Optional[str] = None
    assignee_id: Optional[str] = None
    due_date: datetime


@router.get("/boarding-tasks")
async def list_boarding_tasks(
    plan_id: Optional[str] = None,
    tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db),
):
    stmt = select(BoardingTask).where(BoardingTask.tenant_id == tenant_id)
    if plan_id:
        stmt = stmt.where(BoardingTask.plan_id == plan_id)
    rows = (await db.execute(stmt.order_by(BoardingTask.due_date.asc()).limit(200))).scalars().all()
    return [{
        "id": t.id, "plan_id": t.plan_id, "title": t.title, "description": t.description,
        "assignee_id": t.assignee_id, "status": t.status.value if hasattr(t.status, "value") else str(t.status),
        "due_date": t.due_date.isoformat() if t.due_date else None,
        "is_automated": t.is_automated, "automation_result": t.automation_result,
        "completed_at": t.completed_at.isoformat() if t.completed_at else None,
    } for t in rows]


@router.post("/boarding-tasks", status_code=201)
async def create_boarding_task(
    body: BoardingTaskCreate, tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db),
):
    tenant_id = tenant["tenant_id"]
    plan = await get_or_404(db, BoardingPlan, body.plan_id, tenant_id, detail="Boarding plan not found")
    task = BoardingTask(
        tenant_id=tenant_id, plan_id=body.plan_id, title=body.title, description=body.description,
        assignee_id=body.assignee_id, due_date=body.due_date, status=TaskStatus.PENDING,
    )
    db.add(task)
    plan.total_tasks = (plan.total_tasks or 0) + 1
    db.add(plan)
    await db.commit()
    await db.refresh(task)
    await record_security_event(tenant_id=tenant_id, event_type="MODIFICATION", action="WRITE",
        actor=approver_identity(tenant), actor_role=tenant.get("role"), resource_type="boarding_task", resource_id=task.id)
    return {"id": task.id, "status": task.status.value}


@router.post("/boarding-tasks/{task_id}/transition")
async def transition_boarding_task(
    task_id: str, body: TransitionRequest,
    tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db),
):
    result = await apply_transition(db, WORKFLOW_SPECS["boarding_task"], task_id, body.to_state, tenant, note=body.note)
    if body.to_state in ("COMPLETED", "SKIPPED"):
        # Roll the parent plan's progress counter — derived from the sibling
        # tasks, never user-entered — and auto-close it once every task lands.
        task = (await db.execute(select(BoardingTask).where(BoardingTask.id == task_id))).scalar_one_or_none()
        if task:
            plan = (await db.execute(select(BoardingPlan).where(
                BoardingPlan.id == task.plan_id, BoardingPlan.tenant_id == tenant["tenant_id"]))).scalar_one_or_none()
            if plan:
                done = (await db.execute(select(sqlfunc.count()).select_from(BoardingTask).where(
                    BoardingTask.plan_id == plan.id,
                    BoardingTask.status.in_([TaskStatus.COMPLETED, TaskStatus.SKIPPED]),
                ))).scalar() or 0
                plan.completed_tasks = done
                if plan.total_tasks and done >= plan.total_tasks:
                    plan.status = "COMPLETED"
                db.add(plan)
                await db.commit()
    return result


class OnboardingCheckinBody(BaseModel):
    week_num: int = Field(..., ge=1, le=26)
    response: str = Field("", max_length=4000)


@router.post("/employees/{employee_id}/onboarding-checkin")
async def onboarding_checkin(
    employee_id: str, body: OnboardingCheckinBody,
    tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db),
):
    """Run the Onboarding Agent's week-N check-in through the gated 7-gate
    pipeline. Wires OnboardingAgent, previously bound only to dead org-graph
    metadata (HR_AGENT_REGISTRY['onboarding'])."""
    tenant_id = tenant["tenant_id"]
    await get_or_404(db, HREmployee, employee_id, tenant_id, detail="Employee not found")
    from app.hr.agents.onboarding_agent import OnboardingAgent
    agent = OnboardingAgent()
    result = await agent.check_in_with_new_hire(db, employee_id, body.week_num, body.response)
    await record_security_event(tenant_id=tenant_id, event_type="MODIFICATION", action="EXECUTE",
        actor=approver_identity(tenant), actor_role=tenant.get("role"), resource_type="hr_employee", resource_id=employee_id,
        details={"week_num": body.week_num, "status": result.get("status")})
    return {"employee_id": employee_id, "week_num": body.week_num, **result}


class ExitInterviewBody(BaseModel):
    survey_responses: Dict[str, str]


@router.post("/employees/{employee_id}/offboarding-exit-interview")
async def offboarding_exit_interview(
    employee_id: str, body: ExitInterviewBody,
    tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db),
):
    """Run the Offboarding Agent's exit-interview analysis and persist it onto
    the employee's offboarding plan (creating the plan + an Exit Interview
    task the first time this runs for them). Wires OffboardingAgent,
    previously bound only to dead org-graph metadata."""
    tenant_id = tenant["tenant_id"]
    await get_or_404(db, HREmployee, employee_id, tenant_id, detail="Employee not found")

    from app.hr.agents.offboarding_agent import OffboardingAgent
    from app.hr.agents.gated_runner import extract_decision
    agent = OffboardingAgent()
    # Through the 7-gate pipeline (not the ungated agent method); only trust the
    # analysis when the run cleared every gate.
    result = await agent.execute_via_pipeline(db, tenant_id, {
        "action": "analyze_exit_interview",
        "survey_responses": body.survey_responses,
    })
    status = result.get("status")
    analysis = extract_decision(result) if status == "SUCCESS_CLEAN" else {}

    plan = (await db.execute(select(BoardingPlan).where(
        BoardingPlan.tenant_id == tenant_id, BoardingPlan.employee_id == employee_id,
        BoardingPlan.plan_type == BoardingType.OFFBOARDING,
    ).order_by(BoardingPlan.start_date.desc()))).scalars().first()
    if not plan:
        # Seed the standard offboarding task list so total_tasks reflects the
        # real work (access revocation, equipment return, final pay, exit
        # interview). Completing only the AI exit-interview must not flip a
        # brand-new plan to COMPLETED and hide that nothing else was done.
        plan = BoardingPlan(
            tenant_id=tenant_id, employee_id=employee_id, plan_type=BoardingType.OFFBOARDING,
            start_date=datetime.now(timezone.utc),
            total_tasks=len(_DEFAULT_OFFBOARDING_TASKS), completed_tasks=0, status="ACTIVE",
        )
        db.add(plan)
        await db.flush()
        for title in _DEFAULT_OFFBOARDING_TASKS:
            db.add(BoardingTask(
                tenant_id=tenant_id, plan_id=plan.id, title=title,
                due_date=datetime.now(timezone.utc), status=TaskStatus.PENDING,
            ))
        await db.flush()

    # Case-insensitive match so the seeded "Exit interview" is reused instead of
    # spawning a duplicate "Exit Interview" task.
    task = (await db.execute(select(BoardingTask).where(
        BoardingTask.plan_id == plan.id, sqlfunc.lower(BoardingTask.title) == "exit interview",
    ))).scalars().first()
    if not task:
        task = BoardingTask(
            tenant_id=tenant_id, plan_id=plan.id, title="Exit Interview",
            due_date=datetime.now(timezone.utc), status=TaskStatus.PENDING,
        )
        db.add(task)
        plan.total_tasks = (plan.total_tasks or 0) + 1
        await db.flush()

    # The exit interview is a human survey: record that it was conducted
    # regardless of the model's availability. The gated AI analysis only ENRICHES
    # the task when the run cleared every gate - a down or gate-blocked model must
    # neither fabricate an analysis nor prevent the interview from being logged.
    task.status = TaskStatus.COMPLETED
    task.completed_at = datetime.now(timezone.utc)
    task.is_automated = True
    task.automation_action = "analyze_exit_interview"
    task.automation_result = analysis or {
        "survey_responses": body.survey_responses,
        "ai_analysis": None,
        "summary": "Exit interview recorded. Automated analysis was not applied "
                   "on this run, so no AI insight is attached.",
    }
    db.add(task)

    done = (await db.execute(select(sqlfunc.count()).select_from(BoardingTask).where(
        BoardingTask.plan_id == plan.id, BoardingTask.status.in_([TaskStatus.COMPLETED, TaskStatus.SKIPPED]),
    ))).scalar() or 0
    plan.completed_tasks = done
    if plan.total_tasks and done >= plan.total_tasks:
        plan.status = "COMPLETED"
    db.add(plan)
    await db.commit()

    await record_security_event(tenant_id=tenant_id, event_type="MODIFICATION", action="EXECUTE",
        actor=approver_identity(tenant), actor_role=tenant.get("role"), resource_type="hr_employee", resource_id=employee_id,
        details={"boarding_plan_id": plan.id, "status": status})
    return {"employee_id": employee_id, "boarding_plan_id": plan.id, "task_id": task.id,
            "status": status, "analysis": analysis, "execution_id": _exec_id(result)}
