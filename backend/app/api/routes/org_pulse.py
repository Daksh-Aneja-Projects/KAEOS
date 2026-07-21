"""
KAEOS — Org Pulse (cross-domain intelligence layer)

One call that answers "how is the whole company doing right now": aggregates
the seven domain analytics services, scores each domain's health from its
insight severities, and merges every domain's insights into a single
severity-ranked feed. /activity exposes the cross-domain workflow transition
stream (the same audit trail each domain shows individually).
"""
import logging

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from app.core.database import get_db
from app.core.tenant import get_tenant_id, require_role
from app.core.workflow import find_stale_entities, list_workflow_events
from app.services.workflow_registry import ALL_SPECS

from app.finance.services.analytics import finance_analytics
from app.hr.services.analytics import hr_analytics
from app.sales.services.analytics import sales_analytics
from app.support.services.analytics import support_analytics
from app.operations.services.analytics import operations_analytics
from app.legal.services.analytics import legal_analytics
from app.engineering.services.analytics import engineering_analytics

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/org", tags=["Org Pulse"])

# Sequential on one session by design: AsyncSession is not safe for concurrent
# use, and these are seven fast aggregate queries.
_DOMAIN_ANALYTICS = [
    ("finance", finance_analytics),
    ("hr", hr_analytics),
    ("sales", sales_analytics),
    ("support", support_analytics),
    ("operations", operations_analytics),
    ("legal", legal_analytics),
    ("engineering", engineering_analytics),
]

# Every registered workflow spec across the platform — the SLA sweep walks this.
ALL_WORKFLOW_SPECS = ALL_SPECS

_SEVERITY_PENALTY = {"critical": 25, "warning": 10, "info": 0}
_SEVERITY_RANK = {"critical": 0, "warning": 1, "info": 2}


def _health_score(insights: list[dict]) -> int:
    score = 100
    for ins in insights:
        score -= _SEVERITY_PENALTY.get(ins.get("severity", "info"), 0)
    return max(score, 0)


@router.get("/pulse")
async def org_pulse(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    """Company-wide pulse: per-domain health + KPIs + unified insight feed."""
    domains = []
    all_insights = []
    for name, fn in _DOMAIN_ANALYTICS:
        try:
            data = await fn(db, tenant_id)
        except Exception:
            logger.exception("org_pulse: %s analytics failed", name)
            domains.append({"domain": name, "health": None, "kpis": [], "error": True})
            continue
        insights = data.get("insights", [])
        # "No anomalies" info lines don't belong in the cross-domain feed.
        real_insights = [i for i in insights
                         if i.get("severity") in ("critical", "warning")]
        all_insights.extend({**i, "domain": name} for i in real_insights)
        domains.append({
            "domain": name,
            "health": _health_score(insights),
            "kpis": data.get("kpis", [])[:4],
            "critical_count": sum(1 for i in insights if i.get("severity") == "critical"),
            "warning_count": sum(1 for i in insights if i.get("severity") == "warning"),
        })

    # SLA sweep: breaches surface as insights and dent the owning domain's
    # health (5 points per breached entity, capped at 25 per domain).
    breach_counts: dict[str, int] = {}
    worst: dict[str, dict] = {}
    for spec in ALL_WORKFLOW_SPECS:
        try:
            for b in await find_stale_entities(db, spec, tenant_id, limit=20):
                breach_counts[b["domain"]] = breach_counts.get(b["domain"], 0) + 1
                if b["domain"] not in worst or b["over_by_hours"] > worst[b["domain"]]["over_by_hours"]:
                    worst[b["domain"]] = b
        except Exception:
            logger.exception("org_pulse: SLA sweep failed for %s", spec.entity_type)
    for dom, count in breach_counts.items():
        w = worst[dom]
        all_insights.append({
            "severity": "warning", "domain": dom,
            "message": f"{count} {dom} item(s) past their state SLA - worst: "
                       f"{w['entity_type'].replace('_', ' ')} \"{w['title']}\" stuck in "
                       f"{w['state']} {w['over_by_hours']:.0f}h over target.",
        })
        for d in domains:
            if d["domain"] == dom and d.get("health") is not None:
                d["health"] = max(d["health"] - min(count * 5, 25), 0)
                d["sla_breaches"] = count

    all_insights.sort(key=lambda i: _SEVERITY_RANK.get(i.get("severity", "info"), 3))
    scored = [d["health"] for d in domains if d.get("health") is not None]
    return {
        "org_health": round(sum(scored) / len(scored)) if scored else None,
        "domains": domains,
        "insights": all_insights[:20],
    }


@router.get("/stale")
async def org_stale(
    domain: Optional[str] = None,
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """Every entity sitting past its state's SLA, worst-first, across all
    registered workflows (or one domain)."""
    breaches: list[dict] = []
    for spec in ALL_WORKFLOW_SPECS:
        if domain and spec.domain != domain:
            continue
        try:
            breaches.extend(await find_stale_entities(db, spec, tenant_id))
        except Exception:
            logger.exception("org_stale: sweep failed for %s", spec.entity_type)
    breaches.sort(key=lambda b: b["over_by_hours"], reverse=True)
    return {"count": len(breaches), "breaches": breaches[:100]}


@router.post("/stale/escalate")
async def escalate_stale(
    domain: Optional[str] = None,
    tenant: dict = Depends(require_role("operator")),
    db: AsyncSession = Depends(get_db),
):
    """Turn every current SLA breach into an actionable alert in the activity
    feed (Command Center + WebSocket push). Idempotent: a breach that already
    has an open, un-actioned alert is skipped, so re-running never spams."""
    from app.models.agent_factory import ActivityEventType, ActivityFeedEvent, ActivitySeverity

    tenant_id = tenant["tenant_id"]
    breaches: list[dict] = []
    for spec in ALL_WORKFLOW_SPECS:
        if domain and spec.domain != domain:
            continue
        try:
            breaches.extend(await find_stale_entities(db, spec, tenant_id))
        except Exception:
            logger.exception("escalate_stale: sweep failed for %s", spec.entity_type)

    if not breaches:
        return {"escalated": 0, "skipped_open": 0, "breaches": 0}

    # Dedupe against alerts that are still awaiting action.
    open_q = await db.execute(
        select(ActivityFeedEvent.source_id).where(
            ActivityFeedEvent.tenant_id == tenant_id,
            ActivityFeedEvent.requires_action == True,  # noqa: E712
            # "un-actioned" means the column is False (its default) or NULL —
            # never restrict to just one, or dedupe silently fails.
            (ActivityFeedEvent.action_taken == False)   # noqa: E712
            | (ActivityFeedEvent.action_taken.is_(None)),
            ActivityFeedEvent.source_id.in_([b["entity_id"] for b in breaches]),
        )
    )
    already_open = {row[0] for row in open_q.all()}

    # Persist on the request session (same transaction as the dedupe read);
    # ActivityFeedService opens its own session, which would split the two.
    escalated = 0
    for b in breaches:
        if b["entity_id"] in already_open:
            continue
        db.add(ActivityFeedEvent(
            tenant_id=tenant_id,
            event_type=ActivityEventType.PROACTIVE_ALERT,
            severity=ActivitySeverity.WARNING,
            title=f"SLA breach: {b['entity_type'].replace('_', ' ')} \"{b['title']}\" "
                  f"stuck in {b['state']} ({b['over_by_hours']:.0f}h over target)",
            description=f"{b['domain']} · target {b['sla_hours']}h, current age "
                        f"{b['age_hours']}h. Move it forward or cancel it.",
            source_type=b["entity_type"],
            source_id=b["entity_id"],
            requires_action=True,
            event_metadata={"domain": b["domain"], "state": b["state"],
                            "over_by_hours": b["over_by_hours"]},
        ))
        escalated += 1
    await db.commit()

    if escalated:
        try:
            from app.api.routes.ws import manager as ws_manager
            await ws_manager.broadcast_to_tenant(tenant_id, {
                "type": "sla_escalation", "escalated": escalated,
            })
        except Exception:  # pragma: no cover - broadcast is best-effort
            pass

    return {"escalated": escalated,
            "skipped_open": len(breaches) - escalated,
            "breaches": len(breaches)}


@router.get("/activity")
async def org_activity(
    limit: int = 50,
    domain: Optional[str] = None,
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """Cross-domain workflow transition stream, newest first."""
    return await list_workflow_events(db, tenant_id, domain=domain, limit=limit)
