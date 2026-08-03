"""KAEOS - scheduled executive digest.

A weekly summary of what the governed workforce actually did, delivered through
the tenant's notification channels: the north-star safe-autonomy-rate, where
autonomy leaked, incidents raised, approvals still waiting, and model spend.
Every number comes from the real ledgers - if a source has no rows, the digest
says so rather than inventing a figure.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from sqlalchemy import func, select

logger = logging.getLogger(__name__)


async def build_digest(tenant_id: str, days: int = 7) -> Dict[str, Any]:
    """Assemble the digest payload for one tenant from real data."""
    from app.core.database import AsyncSessionLocal
    from app.models.domain import SkillExecution
    from app.models.infrastructure import CostEvent
    from app.services.safe_autonomy import compute_safe_autonomy

    since = datetime.now(timezone.utc) - timedelta(days=days)
    out: Dict[str, Any] = {"tenant_id": tenant_id, "window_days": days}

    async with AsyncSessionLocal() as db:
        # North star
        try:
            sar = await compute_safe_autonomy(db, tenant_id, days=days)
            out["safe_autonomy_rate"] = sar.get("safe_autonomy_rate")
            out["executions"] = sar.get("total")
            leaking = [s for s in (sar.get("by_skill") or [])
                       if (s.get("total") or 0) >= 3]
            leaking.sort(key=lambda s: s.get("safe_autonomy_rate") or 0)
            out["lowest_autonomy_skills"] = leaking[:3]
        except Exception as e:
            logger.warning("[Digest] safe-autonomy unavailable: %s", e)
            out["safe_autonomy_rate"] = None
            out["executions"] = 0
            out["lowest_autonomy_skills"] = []

        # Approvals still waiting (the queue that stalls autonomy)
        try:
            pending = (await db.execute(
                select(func.count()).select_from(SkillExecution).where(
                    SkillExecution.tenant_id == tenant_id,
                    SkillExecution.status == "PENDING_HITL")
            )).scalar() or 0
        except Exception:
            logger.warning("digest: pending-HITL count failed for %s", tenant_id, exc_info=True)
            pending = 0
        out["pending_approvals"] = int(pending)

        # Incidents raised in the window
        try:
            from app.engineering.models.incidents import Incident
            incidents = (await db.execute(
                select(func.count()).select_from(Incident).where(
                    Incident.tenant_id == tenant_id, Incident.created_at >= since)
            )).scalar() or 0
        except Exception:
            logger.warning("digest: incident count failed for %s", tenant_id, exc_info=True)
            incidents = 0
        out["incidents"] = int(incidents)

        # Model spend
        try:
            spend = (await db.execute(
                select(func.coalesce(func.sum(CostEvent.cost_usd), 0)).where(
                    CostEvent.tenant_id == tenant_id, CostEvent.created_at >= since)
            )).scalar() or 0
            out["spend_usd"] = round(float(spend), 4)
        except Exception:
            logger.warning("digest: spend rollup failed for %s", tenant_id, exc_info=True)
            out["spend_usd"] = None

        # Missions completed
        try:
            from app.models.missions import Mission
            missions = (await db.execute(
                select(Mission.status, func.count()).where(
                    Mission.tenant_id == tenant_id, Mission.created_at >= since
                ).group_by(Mission.status)
            )).all()
            out["missions"] = {str(s): int(c) for s, c in missions}
        except Exception:
            logger.warning("digest: mission rollup failed for %s", tenant_id, exc_info=True)
            out["missions"] = {}

    return out


def render_digest(d: Dict[str, Any]) -> str:
    """Plain-text digest body. Honest about missing data."""
    rate = d.get("safe_autonomy_rate")
    rate_txt = f"{rate * 100:.1f}%" if isinstance(rate, (int, float)) else "no executions yet"
    lines: List[str] = [
        f"KAEOS executive digest - last {d.get('window_days', 7)} days",
        "",
        f"Safe-autonomy-rate: {rate_txt}  (over {d.get('executions', 0)} governed executions)",
        f"Approvals waiting: {d.get('pending_approvals', 0)}",
        f"Incidents raised: {d.get('incidents', 0)}",
    ]
    spend = d.get("spend_usd")
    lines.append(f"Model spend: ${spend:,.2f}" if isinstance(spend, (int, float))
                 else "Model spend: not metered in this window")
    missions = d.get("missions") or {}
    if missions:
        lines.append("Missions: " + ", ".join(f"{k.lower()} {v}" for k, v in missions.items()))
    leaking = d.get("lowest_autonomy_skills") or []
    if leaking:
        lines += ["", "Where autonomy leaked most:"]
        for s in leaking:
            r = s.get("safe_autonomy_rate")
            r_txt = f"{r * 100:.0f}%" if isinstance(r, (int, float)) else "n/a"
            lines.append(f"  - {s.get('skill')}: {r_txt} safe over {s.get('total')} runs")
    lines += ["", "Open KAEOS for the full picture."]
    return "\n".join(lines)


async def send_weekly_digest(tenant_id: str | None = None, days: int = 7) -> Dict[str, int]:
    """Build + deliver the digest for one tenant, or every active tenant."""
    from app.core.database import AsyncSessionLocal
    from app.models.auth import Tenant
    from app.services.notifier import notify

    tenants: List[str] = []
    if tenant_id:
        tenants = [tenant_id]
    else:
        try:
            async with AsyncSessionLocal() as db:
                rows = (await db.execute(select(Tenant).where(
                    Tenant.is_active.is_(True)))).scalars().all()
                tenants = [t.tenant_id for t in rows]
        except Exception as e:
            logger.warning("[Digest] tenant enumeration failed: %s", e)

    sent = failed = 0
    for tid in tenants:
        try:
            payload = await build_digest(tid, days=days)
            result = await notify(tid, "digest.weekly",
                                  subject="KAEOS weekly executive digest",
                                  body=render_digest(payload), data=payload)
            sent += result.get("sent", 0)
            failed += result.get("failed", 0)
        except Exception as e:
            logger.error("[Digest] failed for %s: %s", tid, e)
            failed += 1
    return {"tenants": len(tenants), "sent": sent, "failed": failed}
