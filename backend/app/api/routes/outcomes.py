"""Outcome Intelligence Loop (v3 Phase 2).

Record a measured real-world outcome for a past decision and feed it back into the
executing skill's confidence, then aggregate the impact (distribution, autonomous
vs human decision quality, per-skill). Closes the loop from decision to reality.
"""
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, func, case
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.tenant import get_tenant_id, require_role
from app.core.audit import record_security_event
from app.models.domain import SkillExecution, Skill
from app.models.intelligence_metrics import OutcomeRecord

router = APIRouter(prefix="/outcomes", tags=["Outcomes"])

_VALID = {"GOOD", "BAD", "NEUTRAL"}
_CONF_DELTA = {"GOOD": 0.02, "BAD": -0.05, "NEUTRAL": 0.0}


class OutcomeIn(BaseModel):
    outcome: str
    metric_name: Optional[str] = None
    metric_value: Optional[float] = None
    note: Optional[str] = None


@router.post("/{execution_id}")
async def record_outcome(
    execution_id: str,
    body: OutcomeIn,
    tenant: dict = Depends(require_role("operator")),
    db: AsyncSession = Depends(get_db),
):
    """Record a measured outcome for a past decision. A GOOD outcome nudges the
    executing skill's confidence up, a BAD one down — so the system learns from
    reality, not only from human labels at decision time."""
    outcome = body.outcome.strip().upper()
    if outcome not in _VALID:
        raise HTTPException(status_code=400, detail="outcome must be GOOD, BAD, or NEUTRAL")
    tenant_id = tenant["tenant_id"]

    ex = (await db.execute(
        select(SkillExecution).where(
            SkillExecution.id == execution_id, SkillExecution.tenant_id == tenant_id)
    )).scalar_one_or_none()
    if ex is None:
        raise HTTPException(status_code=404, detail="Execution not found")

    db.add(OutcomeRecord(
        tenant_id=tenant_id, execution_id=execution_id, skill_id_name=ex.skill_id_name,
        outcome=outcome, autonomous=not bool(ex.hitl_required),
        metric_name=body.metric_name, metric_value=body.metric_value, note=body.note,
    ))

    new_conf = None
    delta = _CONF_DELTA[outcome]
    if delta and ex.skill_id_name:
        skill = (await db.execute(
            select(Skill).where(Skill.skill_id == ex.skill_id_name, Skill.tenant_id == tenant_id)
        )).scalar_one_or_none()
        if skill is not None:
            new_conf = round(max(0.1, min(0.99, (skill.confidence or 0.0) + delta)), 4)
            skill.confidence = new_conf

    await db.commit()
    await record_security_event(
        tenant_id=tenant_id, event_type="OUTCOME", action="WRITE",
        actor=tenant.get("name"), actor_role=tenant.get("role"),
        resource_type="skill_execution", resource_id=execution_id,
        details={"outcome": outcome, "new_confidence": new_conf},
    )
    return {"execution_id": execution_id, "outcome": outcome,
            "skill": ex.skill_id_name, "new_confidence": new_conf}


@router.get("/impact")
async def outcome_impact(
    days: int = 30,
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """Aggregate decision outcomes: distribution, autonomous-vs-human decision
    quality, and per-skill outcome quality. Computed from real records."""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    scope = (OutcomeRecord.tenant_id == tenant_id) & (OutcomeRecord.observed_at >= since)

    good = func.count(case((OutcomeRecord.outcome == "GOOD", 1)))
    bad = func.count(case((OutcomeRecord.outcome == "BAD", 1)))
    neutral = func.count(case((OutcomeRecord.outcome == "NEUTRAL", 1)))

    row = (await db.execute(select(func.count(), good, bad, neutral).where(scope))).one()
    total = int(row[0] or 0)

    a_row = (await db.execute(
        select(func.count(), good).where(scope & (OutcomeRecord.autonomous.is_(True)))
    )).one()
    h_row = (await db.execute(
        select(func.count(), good).where(scope & (OutcomeRecord.autonomous.is_(False)))
    )).one()

    per_skill = (await db.execute(
        select(OutcomeRecord.skill_id_name, func.count(), good)
        .where(scope).group_by(OutcomeRecord.skill_id_name).order_by(func.count().desc()).limit(20)
    )).all()

    def _rate(g, t):
        return round(g / t, 4) if t else None

    return {
        "window_days": days,
        "total": total,
        "distribution": {"good": int(row[1] or 0), "bad": int(row[2] or 0), "neutral": int(row[3] or 0)},
        "good_rate": _rate(int(row[1] or 0), total),
        "autonomous": {"total": int(a_row[0] or 0), "good": int(a_row[1] or 0),
                       "good_rate": _rate(int(a_row[1] or 0), int(a_row[0] or 0))},
        "human": {"total": int(h_row[0] or 0), "good": int(h_row[1] or 0),
                  "good_rate": _rate(int(h_row[1] or 0), int(h_row[0] or 0))},
        "by_skill": [{"skill": s or "unknown", "total": int(t or 0), "good_rate": _rate(int(g or 0), int(t or 0))}
                     for s, t, g in per_skill],
        "note": "Outcomes are recorded post-hoc and feed back into skill confidence; null rate = none yet.",
    }
