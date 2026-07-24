"""Enterprise Time Machine (v4 IP-3).

Scrub the org's real decision history and ask "what if we'd decided differently
then?". The timeline is the append-only stream of governed executions; the
north-star (safe-autonomy-rate) is reconstructed AS OF any moment from the
executions up to that point; and a counterfactual re-computes that same metric
with ONE historical decision flipped — a real recomputation over real rows, not a
guess. Honest: nothing is fabricated, and an empty history says so.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import Skill, SkillExecution

_STATUS_CLEAN = "SUCCESS_CLEAN"


def _aware(dt):
    """Coerce a possibly-naive timestamp (SQLite) to aware UTC for safe compares."""
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _is_safe(hitl_required: bool, status: Optional[str]) -> bool:
    return (not hitl_required) and (status == _STATUS_CLEAN)


def _classify(hitl_required: bool, status: Optional[str], outcome_type: Optional[str]) -> str:
    if _is_safe(hitl_required, status):
        return "safe_autonomous"
    if hitl_required:
        return "routed_to_human"
    if (status or "").startswith("FAILED"):
        return "failed"
    if status == "HUMAN_OVERRIDDEN":
        return "overridden"
    if outcome_type == "EDIT":
        return "edited"
    return "other"


async def _window(db: AsyncSession, tenant_id: str, days: int):
    since = datetime.now(timezone.utc) - timedelta(days=days)
    rows = (await db.execute(
        select(SkillExecution.id, SkillExecution.skill_id_name, SkillExecution.status,
               SkillExecution.hitl_required, SkillExecution.outcome_type,
               SkillExecution.started_at, SkillExecution.task_intent)
        .where(SkillExecution.tenant_id == tenant_id, SkillExecution.started_at >= since)
        .order_by(SkillExecution.started_at)
    )).all()
    return rows


def _rate(rows) -> Optional[float]:
    total = len(rows)
    if not total:
        return None
    safe = sum(1 for r in rows if _is_safe(bool(r.hitl_required), r.status))
    return round(safe / total, 4)


async def timeline(db: AsyncSession, tenant_id: str, *, days: int = 45, limit: int = 200) -> dict:
    rows = await _window(db, tenant_id, days)
    skill_dept = {sid: (d or "general").lower() for sid, d in (await db.execute(
        select(Skill.skill_id, Skill.department).where(Skill.tenant_id == tenant_id)
    )).all()}
    events = [
        {
            "execution_id": r.id, "skill_id": r.skill_id_name,
            "department": skill_dept.get(r.skill_id_name, "general"),
            "status": r.status, "hitl_required": bool(r.hitl_required),
            "klass": _classify(bool(r.hitl_required), r.status, r.outcome_type),
            "at": r.started_at.isoformat() if r.started_at else None,
            "intent": (r.task_intent or "")[:120],
        }
        for r in rows
    ]
    # Newest first for the list, but keep chronological order available via `at`.
    events = list(reversed(events))[:limit]
    return {
        "window_days": days,
        "total": len(rows),
        "current_rate": _rate(rows),
        "span": {"from": rows[0].started_at.isoformat() if rows else None,
                 "to": rows[-1].started_at.isoformat() if rows else None},
        "events": events,
    }


async def state_as_of(db: AsyncSession, tenant_id: str, *, at: str, days: int = 45) -> dict:
    try:
        at_dt = datetime.fromisoformat(at.replace("Z", "+00:00"))
    except Exception:
        return {"error": "invalid timestamp"}
    if at_dt.tzinfo is None:
        at_dt = at_dt.replace(tzinfo=timezone.utc)
    rows = await _window(db, tenant_id, days)
    upto = [r for r in rows if r.started_at and _aware(r.started_at) <= at_dt]
    dist: dict[str, int] = {}
    for r in upto:
        k = _classify(bool(r.hitl_required), r.status, r.outcome_type)
        dist[k] = dist.get(k, 0) + 1
    return {
        "as_of": at_dt.isoformat(),
        "decisions_so_far": len(upto),
        "safe_autonomy_rate": _rate(upto),
        "distribution": dist,
    }


async def counterfactual(db: AsyncSession, tenant_id: str, *, execution_id: str,
                         flip: str, days: int = 45) -> dict:
    """Recompute the north-star with ONE historical decision flipped.

    flip = 'approve'  -> treat this decision as if it had run autonomously & cleanly
    flip = 'fail'     -> treat this decision as if it had failed
    flip = 'escalate' -> treat this decision as if it had been routed to a human
    """
    rows = await _window(db, tenant_id, days)
    if not rows:
        return {"error": "no decision history in window"}
    target = next((r for r in rows if r.id == execution_id), None)
    if target is None:
        return {"error": "execution not in window"}

    before = _rate(rows)

    # Build the counterfactual classification for the target only.
    def _cf_safe(r):
        if r.id != execution_id:
            return _is_safe(bool(r.hitl_required), r.status)
        if flip == "approve":
            return True
        if flip in ("fail", "escalate"):
            return False
        return _is_safe(bool(r.hitl_required), r.status)

    total = len(rows)
    after_safe = sum(1 for r in rows if _cf_safe(r))
    after = round(after_safe / total, 4) if total else None

    desc_map = {
        "approve": "had run autonomously and cleanly",
        "fail": "had failed",
        "escalate": "had been routed to a human",
    }
    return {
        "execution_id": execution_id,
        "skill_id": target.skill_id_name,
        "original_klass": _classify(bool(target.hitl_required), target.status, target.outcome_type),
        "flip": flip,
        "window_days": days,
        "before_rate": before,
        "after_rate": after,
        "delta": round((after - before), 4) if (after is not None and before is not None) else None,
        "description": f"If '{target.skill_id_name}' {desc_map.get(flip, 'were different')}, "
                       f"the safe-autonomy-rate over the window would be {after}.",
    }
