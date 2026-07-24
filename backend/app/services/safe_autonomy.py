"""KAEOS - Safe Autonomy Rate.

The north-star metric, computed from REAL logged executions (never seeded):

    safe_autonomy_rate = (executions run autonomously AND cleanly) / (all executions)

"Autonomously" = the confidence/HITL gate did not route it to a human
(``hitl_required == False``). "Cleanly" = it succeeded without a human override,
edit, or failure (``status == "SUCCESS_CLEAN"``). An action that needed a human,
was overridden, was edited, or failed does NOT count toward safe autonomy - and
the breakdown says exactly which of those it was, so the number is explainable,
not just asserted.

Everything here is derived from the ``skill_executions`` table at query time.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import SkillExecution

# Fallout reasons: why an execution did NOT count as safe-autonomous.
_STATUS_CLEAN = "SUCCESS_CLEAN"
_STATUS_OVERRIDDEN = "HUMAN_OVERRIDDEN"
_OUTCOME_EDIT = "SUCCESS_WITH_EDIT"


def _rate(numerator: int, denominator: int) -> Optional[float]:
    return round(numerator / denominator, 4) if denominator else None


def _classify_counts():
    """SQL count expressions shared by the overall and per-skill rollups."""
    autonomous_safe = func.count(case(
        ((SkillExecution.hitl_required.is_(False)) & (SkillExecution.status == _STATUS_CLEAN), 1)
    ))
    routed_to_human = func.count(case((SkillExecution.hitl_required.is_(True), 1)))
    overridden = func.count(case((SkillExecution.status == _STATUS_OVERRIDDEN, 1)))
    edited = func.count(case((SkillExecution.outcome_type == _OUTCOME_EDIT, 1)))
    failed = func.count(case((SkillExecution.status.like("FAILED%"), 1)))
    return autonomous_safe, routed_to_human, overridden, edited, failed


async def compute_safe_autonomy(db: AsyncSession, tenant_id: str, days: int = 30) -> dict[str, Any]:
    """Compute the safe-autonomy-rate and its explainable breakdown for a tenant."""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    scope = (SkillExecution.tenant_id == tenant_id) & (SkillExecution.started_at >= since)

    autonomous_safe, routed_to_human, overridden, edited, failed = _classify_counts()
    row = (await db.execute(
        select(
            func.count().label("total"),
            autonomous_safe.label("autonomous_safe"),
            routed_to_human.label("routed_to_human"),
            overridden.label("overridden"),
            edited.label("edited"),
            failed.label("failed"),
        ).where(scope)
    )).one()

    total = int(row.total or 0)
    safe = int(row.autonomous_safe or 0)

    # Per-skill breakdown (where autonomy is leaking).
    per_skill_rows = (await db.execute(
        select(
            SkillExecution.skill_id_name.label("skill"),
            func.count().label("total"),
            autonomous_safe.label("safe"),
        ).where(scope).group_by(SkillExecution.skill_id_name).order_by(func.count().desc()).limit(50)
    )).all()
    by_skill = [
        {
            "skill": r.skill or "unknown",
            "total": int(r.total or 0),
            "safe_autonomy_rate": _rate(int(r.safe or 0), int(r.total or 0)),
        }
        for r in per_skill_rows
    ]

    # Daily time-series.
    day = func.date(SkillExecution.started_at)
    ts_rows = (await db.execute(
        select(day.label("day"), func.count().label("total"), autonomous_safe.label("safe"))
        .where(scope).group_by(day).order_by(day)
    )).all()
    timeseries = [
        {"date": str(r.day), "total": int(r.total or 0),
         "safe_autonomy_rate": _rate(int(r.safe or 0), int(r.total or 0))}
        for r in ts_rows
    ]

    return {
        "tenant_id": tenant_id,
        "window_days": days,
        "total_executions": total,
        "safe_autonomous": safe,
        "safe_autonomy_rate": _rate(safe, total),
        "fallout": {
            "routed_to_human": int(row.routed_to_human or 0),
            "human_overridden": int(row.overridden or 0),
            "human_edited": int(row.edited or 0),
            "failed": int(row.failed or 0),
        },
        "by_skill": by_skill,
        "timeseries": timeseries,
        "note": "Computed from logged skill executions; null rate means no executions in window.",
    }
