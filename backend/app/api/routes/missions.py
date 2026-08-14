"""Cross-Domain Autonomous Missions API (v3 Phase 3).

A plain-language goal becomes a governed DAG of real skills across departments,
with a budget gate, HITL checkpoints, and a mission ledger. Operators launch and
drive missions; the engine still runs every step through the 7 gates.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.tenant import check_department_scope, get_tenant, get_tenant_id, require_role
from app.core.audit import record_security_event
from app.models.missions import Mission, MissionStep, MissionEvent
from app.services.missions import (
    plan_mission, abort_mission, resolve_hitl_step, start_mission_run,
)

router = APIRouter(prefix="/missions", tags=["Missions"])


class MissionIn(BaseModel):
    goal: str
    budget_usd: Optional[float] = None


class HitlIn(BaseModel):
    approved: bool


@router.post("")
async def create_mission(
    body: MissionIn,
    tenant: dict = Depends(require_role("operator")),
    db: AsyncSession = Depends(get_db),
):
    """Plan a mission from a goal: decompose into a governed DAG of real skills."""
    goal = (body.goal or "").strip()
    if not goal:
        raise HTTPException(status_code=400, detail="goal is required")
    if body.budget_usd is not None and body.budget_usd < 0:
        raise HTTPException(status_code=400, detail="budget_usd must be >= 0")
    tenant_id = tenant["tenant_id"]
    # Coerce the budget cap to Decimal at the trust boundary: it is compared
    # against Decimal-accumulated spent_usd, and asyncpg can round/raise on a
    # raw float bound to a Numeric column.
    from decimal import Decimal
    budget = Decimal(str(body.budget_usd)) if body.budget_usd is not None else None
    mission = await plan_mission(
        db, tenant_id=tenant_id, goal=goal,
        budget_usd=budget, created_by=tenant.get("name"))
    await record_security_event(
        tenant_id=tenant_id, event_type="MISSION", action="PLAN",
        actor=tenant.get("name"), actor_role=tenant.get("role"),
        resource_type="mission", resource_id=mission.id,
        details={"goal": goal, "status": mission.status})
    return await _detail(db, tenant_id, mission.id)


@router.get("")
async def list_missions(
    limit: int = 50,
    tenant: dict = Depends(get_tenant),
    db: AsyncSession = Depends(get_db),
):
    tenant_id = tenant["tenant_id"]
    limit = max(1, min(200, limit))
    rows = (await db.execute(
        select(Mission).where(Mission.tenant_id == tenant_id)
        .order_by(Mission.created_at.desc()).limit(limit)
    )).scalars().all()
    # Department-scoped users see only missions that touch their department.
    scope = tenant.get("department")
    if scope:
        rows = [m for m in rows if scope in (m.departments or [])]
    return {
        "missions": [
            {"id": m.id, "goal": m.goal, "status": m.status,
             "departments": m.departments, "budget_usd": m.budget_usd,
             "spent_usd": round(m.spent_usd or 0.0, 4),
             "created_at": m.created_at.isoformat() if m.created_at else None}
            for m in rows
        ]
    }


@router.get("/{mission_id}")
async def get_mission(
    mission_id: str,
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    detail = await _detail(db, tenant_id, mission_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="mission not found")
    return detail


async def _guard_mission_scope(db: AsyncSession, tenant: dict, mission_id: str,
                               step_seq: Optional[int] = None) -> None:
    """Department-scoped callers may only ACT on work inside their scope.

    - step action (HITL): the step's own department must match the scope.
    - whole-mission action (advance/abort): every department the mission spans
      must be within scope - advancing a cross-department mission executes
      other departments' steps, which a scoped user must not be able to do.
    Org-wide callers (no scope) pass untouched.
    """
    scope = tenant.get("department")
    if not scope:
        return
    if step_seq is not None:
        step = (await db.execute(
            select(MissionStep).where(MissionStep.mission_id == mission_id,
                                      MissionStep.seq == step_seq)
        )).scalar_one_or_none()
        if step is not None:
            check_department_scope(tenant, step.department)
        return
    mission = (await db.execute(
        select(Mission).where(Mission.id == mission_id,
                              Mission.tenant_id == tenant["tenant_id"])
    )).scalar_one_or_none()
    if mission is not None:
        for dept in (mission.departments or []):
            check_department_scope(tenant, dept)


@router.post("/{mission_id}/advance")
async def advance(
    mission_id: str,
    tenant: dict = Depends(require_role("operator")),
    db: AsyncSession = Depends(get_db),
):
    await _guard_mission_scope(db, tenant, mission_id)
    """Start (or resume) the mission's background runner and return immediately.
    A gated step can take a while on a real model, so execution runs in the
    background and the UI polls GET /missions/{id} for live progress."""
    detail = await _detail(db, tenant["tenant_id"], mission_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="mission not found")
    if detail["status"] in ("PLANNING", "RUNNING"):
        await start_mission_run(tenant["tenant_id"], mission_id)
        detail = await _detail(db, tenant["tenant_id"], mission_id)
    return detail


@router.post("/{mission_id}/steps/{seq}/hitl")
async def resolve_hitl(
    mission_id: str, seq: int, body: HitlIn,
    tenant: dict = Depends(require_role("operator")),
    db: AsyncSession = Depends(get_db),
):
    await _guard_mission_scope(db, tenant, mission_id, step_seq=seq)
    res = await resolve_hitl_step(
        db, tenant_id=tenant["tenant_id"], mission_id=mission_id, seq=seq,
        approved=body.approved, approver=tenant.get("name"))
    if res.get("error"):
        raise HTTPException(status_code=400, detail=res["error"])
    await record_security_event(
        tenant_id=tenant["tenant_id"], event_type="MISSION",
        action="HITL_APPROVE" if body.approved else "HITL_REJECT",
        actor=tenant.get("name"), actor_role=tenant.get("role"),
        resource_type="mission_step", resource_id=f"{mission_id}:{seq}")
    # On approval the mission is RUNNING again — resume it in the background.
    if body.approved and res.get("status") == "RUNNING":
        await start_mission_run(tenant["tenant_id"], mission_id)
    return await _detail(db, tenant["tenant_id"], mission_id)


@router.post("/{mission_id}/abort")
async def abort(
    mission_id: str,
    tenant: dict = Depends(require_role("operator")),
    db: AsyncSession = Depends(get_db),
):
    await _guard_mission_scope(db, tenant, mission_id)
    res = await abort_mission(db, tenant_id=tenant["tenant_id"], mission_id=mission_id,
                              actor=tenant.get("name"))
    if res.get("error"):
        raise HTTPException(status_code=404, detail=res["error"])
    await record_security_event(
        tenant_id=tenant["tenant_id"], event_type="MISSION", action="ABORT",
        actor=tenant.get("name"), actor_role=tenant.get("role"),
        resource_type="mission", resource_id=mission_id)
    return await _detail(db, tenant["tenant_id"], mission_id)


async def _detail(db: AsyncSession, tenant_id: str, mission_id: str) -> Optional[dict]:
    mission = (await db.execute(
        select(Mission).where(Mission.id == mission_id, Mission.tenant_id == tenant_id)
    )).scalar_one_or_none()
    if mission is None:
        return None
    steps = (await db.execute(
        select(MissionStep).where(MissionStep.mission_id == mission_id)
        .order_by(MissionStep.seq)
    )).scalars().all()
    events = (await db.execute(
        select(MissionEvent).where(MissionEvent.mission_id == mission_id)
        .order_by(MissionEvent.created_at)
    )).scalars().all()
    return {
        "id": mission.id, "goal": mission.goal, "status": mission.status,
        "narrative": mission.narrative, "departments": mission.departments,
        "budget_usd": mission.budget_usd, "spent_usd": round(mission.spent_usd or 0.0, 4),
        "created_by": mission.created_by,
        "created_at": mission.created_at.isoformat() if mission.created_at else None,
        "completed_at": mission.completed_at.isoformat() if mission.completed_at else None,
        "steps": [
            {"seq": s.seq, "name": s.name, "department": s.department,
             "skill_id": s.skill_id, "confidence": round(s.confidence or 0.0, 3),
             "depends_on": s.depends_on or [], "hitl_required": s.hitl_required,
             "status": s.status, "execution_id": s.execution_id,
             "result_summary": s.result_summary, "cost_usd": round(s.cost_usd or 0.0, 4)}
            for s in steps
        ],
        "ledger": [
            {"kind": e.kind, "message": e.message, "step_seq": e.step_seq,
             "at": e.created_at.isoformat() if e.created_at else None}
            for e in events
        ],
    }
