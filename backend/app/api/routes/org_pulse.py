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
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from app.core.database import get_db
from app.core.tenant import get_tenant_id
from app.core.workflow import list_workflow_events

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

    all_insights.sort(key=lambda i: _SEVERITY_RANK.get(i.get("severity", "info"), 3))
    scored = [d["health"] for d in domains if d.get("health") is not None]
    return {
        "org_health": round(sum(scored) / len(scored)) if scored else None,
        "domains": domains,
        "insights": all_insights[:20],
    }


@router.get("/activity")
async def org_activity(
    limit: int = 50,
    domain: Optional[str] = None,
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """Cross-domain workflow transition stream, newest first."""
    return await list_workflow_events(db, tenant_id, domain=domain, limit=limit)
