"""Causal Discovery (v4 IP-6).

Surfaces likely causal relationships between departments from real operational
data — no LLM, no hand-authored graph. It builds each department's daily
adverse-event series (failed / blocked / overridden executions) and measures
LAGGED cross-correlation: if a rise in department A's trouble on day t reliably
precedes department B's trouble on day t+1, that is evidence of A → B ("attrition
in Eng → deploy delays → SLA breaches"). Honest: too little history returns
`insufficient`, and only links above a strength floor are reported.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import Skill, SkillExecution

_ADVERSE_PREFIXES = ("FAILED", "BLOCKED", "HUMAN_OVERRIDDEN", "TIMEOUT", "ERROR")


def _is_adverse(status: Optional[str]) -> bool:
    s = (status or "").upper()
    return any(s.startswith(p) for p in _ADVERSE_PREFIXES)


def _pearson(xs: list[float], ys: list[float]) -> Optional[float]:
    n = len(xs)
    if n < 3:
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx == 0 or syy == 0:
        return None
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    return sxy / math.sqrt(sxx * syy)


async def _adverse_series(db: AsyncSession, tenant_id: str, days: int):
    """Return (date_axis, {department: [adverse_count per day]})."""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    # Map skill -> department.
    skill_dept = {
        sid: (dept or "general").lower()
        for sid, dept in (await db.execute(
            select(Skill.skill_id, Skill.department).where(Skill.tenant_id == tenant_id)
        )).all()
    }
    day = func.date(SkillExecution.started_at)
    rows = (await db.execute(
        select(day.label("d"), SkillExecution.skill_id_name, SkillExecution.status)
        .where(SkillExecution.tenant_id == tenant_id, SkillExecution.started_at >= since)
    )).all()

    counts: dict[str, dict[str, int]] = {}   # dept -> {date: adverse_count}
    date_set = set()
    for d, sid, status in rows:
        date_set.add(str(d))
        if _is_adverse(status):
            dept = skill_dept.get(sid, "general")
            counts.setdefault(dept, {}).setdefault(str(d), 0)
            counts[dept][str(d)] += 1

    axis = sorted(date_set)
    series = {dept: [dmap.get(dt, 0) for dt in axis] for dept, dmap in counts.items()}
    return axis, series


async def discover(db: AsyncSession, tenant_id: str, *, days: int = 45,
                   min_days: int = 6, min_strength: float = 0.4) -> dict:
    axis, series = await _adverse_series(db, tenant_id, days)
    if len(axis) < min_days:
        return {"insufficient": True, "reason": f"need >= {min_days} days of activity, have {len(axis)}",
                "window_days": days, "nodes": [], "links": []}

    depts = [d for d, s in series.items() if sum(s) > 0]
    nodes = [{"id": d, "label": d, "adverse_total": sum(series[d])} for d in depts]

    links = []
    for a in depts:
        for b in depts:
            if a == b:
                continue
            xa, yb = series[a], series[b]
            # lag-1: A[t] vs B[t+1] (A precedes B)
            lag1 = _pearson(xa[:-1], yb[1:]) if len(xa) > 3 else None
            lag0 = _pearson(xa, yb)
            best_lag, best = (1, lag1) if (lag1 is not None and (lag0 is None or abs(lag1) >= abs(lag0))) else (0, lag0)
            if best is not None and best >= min_strength:
                links.append({
                    "source": a, "target": b,
                    "strength": round(best, 3), "lag_days": best_lag,
                    "samples": len(axis),
                    "kind": "leads" if best_lag == 1 else "co-occurs",
                })
    # De-dup contemporaneous (lag-0) mirror pairs, keep the stronger direction.
    links.sort(key=lambda l: -l["strength"])
    seen_co = set()
    deduped = []
    for l in links:
        if l["lag_days"] == 0:
            key = tuple(sorted((l["source"], l["target"])))
            if key in seen_co:
                continue
            seen_co.add(key)
        deduped.append(l)

    return {
        "insufficient": False,
        "window_days": days,
        "nodes": sorted(nodes, key=lambda n: -n["adverse_total"]),
        "links": deduped,
        "method": "lagged Pearson cross-correlation on daily adverse-event counts",
        "note": "A 'leads' link means A's trouble precedes B's by a day; strength is the correlation.",
    }
