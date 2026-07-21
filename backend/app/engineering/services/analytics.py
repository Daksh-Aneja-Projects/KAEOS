"""
KAEOS Engineering — Analytics Service
Incident MTTA/MTTR, severity mix, deployment success rate and PR flow,
computed live from tenant rows.
"""
from sqlalchemy import func as sqlfunc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.engineering.models.delivery import Deployment, PRStatus, PullRequest
from app.engineering.models.incidents import Incident, IncidentStatus

_OPEN_INCIDENTS = [IncidentStatus.DETECTED, IncidentStatus.TRIAGED,
                   IncidentStatus.MITIGATING, IncidentStatus.MONITORING]


async def engineering_analytics(db: AsyncSession, tenant_id: str) -> dict:
    sev_q = await db.execute(
        select(Incident.severity, sqlfunc.count())
        .where(Incident.tenant_id == tenant_id)
        .group_by(Incident.severity)
    )
    by_severity = [{"label": (s.value if hasattr(s, "value") else str(s)), "value": int(c)}
                   for s, c in sev_q.all()]

    open_q = await db.execute(
        select(sqlfunc.count())
        .where(Incident.tenant_id == tenant_id, Incident.status.in_(_OPEN_INCIDENTS))
    )
    open_incidents = int(open_q.scalar() or 0)

    mtta_q = await db.execute(
        select(sqlfunc.avg(Incident.time_to_acknowledge_mins),
               sqlfunc.avg(Incident.time_to_resolve_mins))
        .where(Incident.tenant_id == tenant_id)
    )
    mtta, mttr = mtta_q.one()

    dep_q = await db.execute(
        select(Deployment.status, sqlfunc.count())
        .where(Deployment.tenant_id == tenant_id)
        .group_by(Deployment.status)
    )
    dep_counts = {(s.value if hasattr(s, "value") else str(s)): int(c) for s, c in dep_q.all()}
    dep_done = dep_counts.get("SUCCEEDED", 0) + dep_counts.get("FAILED", 0) + dep_counts.get("ROLLED_BACK", 0)
    deploy_success = (dep_counts.get("SUCCEEDED", 0) / dep_done * 100) if dep_done else None

    pr_q = await db.execute(
        select(PullRequest.status, sqlfunc.count())
        .where(PullRequest.tenant_id == tenant_id)
        .group_by(PullRequest.status)
    )
    pr_counts = {(s.value if hasattr(s, "value") else str(s)): int(c) for s, c in pr_q.all()}
    open_prs = sum(pr_counts.get(s, 0) for s in ["OPEN", "IN_REVIEW", "CHANGES_REQUESTED", "APPROVED"])

    risky_pr_q = await db.execute(
        select(sqlfunc.count())
        .where(PullRequest.tenant_id == tenant_id,
               PullRequest.status.in_([PRStatus.OPEN, PRStatus.IN_REVIEW]),
               (PullRequest.touches_auth == True) | (PullRequest.touches_migrations == True))  # noqa: E712
    )
    risky_open_prs = int(risky_pr_q.scalar() or 0)

    pending_deploys = dep_counts.get("PENDING_APPROVAL", 0)

    insights = []
    if open_incidents:
        insights.append({"severity": "critical" if open_incidents > 2 else "warning",
                         "message": f"{open_incidents} incidents are open right now."})
    if deploy_success is not None and deploy_success < 90 and dep_done >= 5:
        insights.append({"severity": "warning",
                         "message": f"Deployment success rate is {deploy_success:.0f}% — below the 90% bar."})
    if risky_open_prs:
        insights.append({"severity": "warning",
                         "message": f"{risky_open_prs} open PRs touch auth or migrations — prioritize review."})
    if pending_deploys:
        insights.append({"severity": "info",
                         "message": f"{pending_deploys} deployments are waiting for approval."})
    if not insights:
        insights.append({"severity": "info", "message": "Delivery pipeline is green."})

    return {
        "domain": "engineering",
        "kpis": [
            {"key": "open_incidents", "label": "Open Incidents", "value": open_incidents, "format": "number"},
            {"key": "mtta", "label": "MTTA", "value": float(mtta) / 60 if mtta is not None else None, "format": "hours"},
            {"key": "mttr", "label": "MTTR", "value": float(mttr) / 60 if mttr is not None else None, "format": "hours"},
            {"key": "deploy_success", "label": "Deploy Success", "value": deploy_success, "format": "percent"},
            {"key": "open_prs", "label": "Open PRs", "value": open_prs, "format": "number"},
            {"key": "pending_deploys", "label": "Deploys Awaiting Approval", "value": pending_deploys, "format": "number"},
        ],
        "charts": [
            {"key": "severity", "title": "Incidents by Severity", "type": "bar", "items": by_severity},
            {"key": "deploys", "title": "Deployments by Status", "type": "donut",
             "items": [{"label": k, "value": v} for k, v in dep_counts.items()]},
            {"key": "prs", "title": "Pull Requests by Status", "type": "bar",
             "items": [{"label": k, "value": v} for k, v in pr_counts.items()]},
        ],
        "insights": insights,
    }
