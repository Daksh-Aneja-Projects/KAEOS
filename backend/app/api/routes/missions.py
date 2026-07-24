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
from app.core.tenant import get_tenant_id, require_role
from app.core.audit import record_security_event
from app.models.missions import Mission, MissionStep, MissionEvent
from app.services.missions import plan_mission, advance_mission, abort_mission, resolve_hitl_step

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
    mission = await plan_mission(
        db, tenant_id=tenant_id, goal=goal,
        budget_usd=body.budget_usd, created_by=tenant.get("name"))
    await record_security_event(
        tenant_id=tenant_id, event_type="MISSION", action="PLAN",
        actor=tenant.get("name"), actor_role=tenant.get("role"),
        resource_type="mission", resource_id=mission.id,
        details={"goal": goal, "status": mission.status})
    return await _detail(db, tenant_id, mission.id)


@router.get("")
async def list_missions(
    limit: int = 50,
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    limit = max(1, min(200, limit))
    rows = (await db.execute(
        select(Mission).where(Mission.tenant_id == tenant_id)
        .order_by(Mission.created_at.desc()).limit(limit)
    )).scalars().all()
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


@router.post("/{mission_id}/advance")
async def advance(
    mission_id: str,
    tenant: dict = Depends(require_role("operator")),
    db: AsyncSession = Depends(get_db),
):
    res = await advance_mission(db, tenant_id=tenant["tenant_id"], mission_id=mission_id)
    if res.get("error"):
        raise HTTPException(status_code=404, detail=res["error"])
    return await _detail(db, tenant["tenant_id"], mission_id)


@router.post("/{mission_id}/steps/{seq}/hitl")
async def resolve_hitl(
    mission_id: str, seq: int, body: HitlIn,
    tenant: dict = Depends(require_role("operator")),
    db: AsyncSession = Depends(get_db),
):
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
    return await _detail(db, tenant["tenant_id"], mission_id)


@router.post("/{mission_id}/abort")
async def abort(
    mission_id: str,
    tenant: dict = Depends(require_role("operator")),
    db: AsyncSession = Depends(get_db),
):
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
