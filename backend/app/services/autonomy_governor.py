"""L5-reverse closed loop — the autonomy governor.

The forward path is wired: an executive sets a per-domain ``min_confidence`` and
Gate 3 enforces it. Nothing wrote that dial back FROM the measured outcome, so the
system could not tighten or relax autonomy on its own evidence.

This governor nudges each domain's dial from the real safe-autonomy-rate and its
override/failure fallout, within a bounded band and in small steps (no wild
swings). It only manages dials flagged ``auto_managed`` — a human setting the dial
via /config/autonomy flips that off, so an explicit executive decision is never
overridden (human override wins).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, func, case
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import Skill, SkillExecution
from app.models.settings import AutonomyPolicy

logger = logging.getLogger(__name__)

# Tuning — deliberately conservative so the dial drifts, never lurches.
_WINDOW_DAYS = 30
_MIN_SAMPLES = 20          # need enough evidence before touching a dial
_STEP = 0.02              # per-run nudge
_FLOOR, _CEILING = 0.60, 0.95
_GOOD_RATE = 0.90         # relax autonomy above this...
_LOW_FALLOUT = 0.05       # ...only if bad outcomes are rare
_BAD_FALLOUT = 0.20       # tighten autonomy when overrides+failures exceed this

_STATUS_OVERRIDDEN = "HUMAN_OVERRIDDEN"


def _clamp(v: float) -> float:
    return round(max(_FLOOR, min(_CEILING, v)), 4)


async def run_autonomy_governor(db: AsyncSession, tenant_id: str) -> dict:
    """Adjust every auto-managed domain dial for one tenant. Returns a receipt."""
    from app.core.config import get_settings
    default = float(get_settings().CONFIDENCE_AUTONOMOUS_EXEC)
    since = datetime.now(timezone.utc) - timedelta(days=_WINDOW_DAYS)

    # Per-domain execution outcomes (domain = the executed skill's department).
    safe = func.count(case((
        (SkillExecution.hitl_required.is_(False)) &
        (SkillExecution.status.in_(("SUCCESS_CLEAN", "SUCCESS"))), 1)))
    overridden = func.count(case((SkillExecution.status == _STATUS_OVERRIDDEN, 1)))
    failed = func.count(case((SkillExecution.status.like("FAILED%"), 1)))

    rows = (await db.execute(
        select(
            func.lower(Skill.department).label("domain"),
            func.count().label("total"),
            safe.label("safe"),
            overridden.label("overridden"),
            failed.label("failed"),
        )
        .join(Skill, Skill.skill_id == SkillExecution.skill_id_name)
        .where(SkillExecution.tenant_id == tenant_id,
               SkillExecution.started_at >= since,
               Skill.tenant_id == tenant_id,
               Skill.department.isnot(None))
        .group_by(func.lower(Skill.department))
    )).all()

    # Existing policies for this tenant, keyed by domain.
    policies = {p.domain: p for p in (await db.execute(
        select(AutonomyPolicy).where(AutonomyPolicy.tenant_id == tenant_id)
    )).scalars().all()}

    changes = []
    for r in rows:
        domain, total = r.domain, int(r.total or 0)
        if not domain or total < _MIN_SAMPLES:
            continue
        rate = int(r.safe or 0) / total
        bad_fraction = (int(r.overridden or 0) + int(r.failed or 0)) / total

        existing = policies.get(domain)
        # Never override a human-set dial.
        if existing is not None and not existing.auto_managed:
            continue

        current = existing.min_confidence if existing is not None else default
        if bad_fraction >= _BAD_FALLOUT:
            target = _clamp(current + _STEP)           # tighten: demand more confidence
        elif rate >= _GOOD_RATE and bad_fraction <= _LOW_FALLOUT:
            target = _clamp(current - _STEP)           # relax: allow more autonomy
        else:
            continue                                    # stable band — leave it

        if abs(target - current) < 1e-6:
            continue                                    # already at the bound

        if existing is not None:
            existing.min_confidence = target
            existing.auto_managed = True
        else:
            db.add(AutonomyPolicy(tenant_id=tenant_id, domain=domain,
                                  min_confidence=target, auto_managed=True))
        changes.append({"domain": domain, "from": round(current, 4), "to": target,
                        "rate": round(rate, 4), "bad_fraction": round(bad_fraction, 4)})

    if changes:
        await db.commit()
        try:
            from app.services.autonomy_policy import invalidate
            for c in changes:
                invalidate(tenant_id, c["domain"])
        except Exception as e:
            # Cache invalidation is an optimization: the policies are committed
            # and the cache entries expire within their short TTL, so this
            # delays the new thresholds by seconds, never loses them.
            logger.warning(f"[autonomy-governor] cache invalidation failed: {e}")
    return {"tenant_id": tenant_id, "adjusted": len(changes), "changes": changes}
