"""
KAEOS Engineering Domain — API v1

Engineering + IT Ops surface: service catalog, pull requests, deployments,
incidents, postmortems, dashboard, and the three gated AI agents.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func as sqlfunc
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.tenant import get_tenant_id, require_role
from app.core.audit import record_security_event
from app.engineering.agents.code_review_agent import CodeReviewAgent
from app.engineering.agents.deploy_risk_agent import DeployRiskAgent
from app.engineering.agents.incident_agent import IncidentAgent
from app.engineering.models.core import Engineer, Service
from app.engineering.models.delivery import Deployment, PullRequest
from app.engineering.models.incidents import Incident, Postmortem

import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/engineering", tags=["Engineering & IT Ops"])


def _enum(v):
    return v.value if hasattr(v, "value") else v


# ── Dashboard ─────────────────────────────────────────────────────────────────

@router.get("/dashboard")
async def engineering_dashboard(
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """DORA-flavoured posture, computed from live rows (no hardcoded metrics)."""
    services = (await db.execute(
        select(Service).where(Service.tenant_id == tenant_id)
    )).scalars().all()
    prs = (await db.execute(
        select(PullRequest).where(PullRequest.tenant_id == tenant_id)
    )).scalars().all()
    deploys = (await db.execute(
        select(Deployment).where(Deployment.tenant_id == tenant_id)
    )).scalars().all()
    incidents = (await db.execute(
        select(Incident).where(Incident.tenant_id == tenant_id)
    )).scalars().all()

    open_prs = [p for p in prs if _enum(p.status) in ("OPEN", "IN_REVIEW", "CHANGES_REQUESTED")]
    succeeded = [d for d in deploys if _enum(d.status) == "SUCCEEDED"]
    failed = [d for d in deploys if _enum(d.status) in ("FAILED", "ROLLED_BACK")]
    open_incidents = [i for i in incidents if _enum(i.status) not in ("RESOLVED", "CLOSED")]
    resolved = [i for i in incidents if i.time_to_resolve_mins is not None]

    change_fail_rate = (
        round(len(failed) / len(deploys) * 100, 1) if deploys else None
    )
    mttr = (
        round(sum(i.time_to_resolve_mins for i in resolved) / len(resolved), 1)
        if resolved else None
    )
    unhealthy = [s for s in services if _enum(s.health) != "HEALTHY"]

    return {
        "total_services": len(services),
        "unhealthy_services": len(unhealthy),
        "open_pull_requests": len(open_prs),
        "prs_awaiting_review": len([p for p in open_prs if (p.approvals or 0) == 0]),
        "deployments_total": len(deploys),
        "deployments_succeeded": len(succeeded),
        "change_failure_rate_pct": change_fail_rate,
        "open_incidents": len(open_incidents),
        "sev1_open": len([i for i in open_incidents if _enum(i.severity) == "SEV1"]),
        "mttr_minutes": mttr,
        "postmortems_due": len([i for i in incidents if _enum(i.status) == "POSTMORTEM_DUE"]),
        "engineers_on_call": (await db.execute(
            select(sqlfunc.count()).select_from(Engineer).where(
                Engineer.tenant_id == tenant_id, Engineer.on_call == True  # noqa: E712
            )
        )).scalar() or 0,
    }


# ── Service catalog ───────────────────────────────────────────────────────────

@router.get("/services")
async def list_services(
    tenant_id: str = Depends(get_tenant_id),
    health: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    q = select(Service).where(Service.tenant_id == tenant_id)
    if health:
        q = q.where(Service.health == health)
    services = (await db.execute(q.order_by(Service.name).limit(200))).scalars().all()
    return [{
        "id": s.id, "name": s.name, "slug": s.slug, "description": s.description,
        "tier": _enum(s.tier), "health": _enum(s.health),
        "owning_squad": s.owning_squad, "repo_url": s.repo_url,
        "slo_target": s.slo_availability_target, "slo_actual": s.slo_availability_actual,
        "error_budget_remaining_pct": s.error_budget_remaining_pct,
        "deploys_last_30d": s.deploys_last_30d, "open_incidents": s.open_incidents,
    } for s in services]


@router.get("/services/{service_id}")
async def get_service(
    service_id: str,
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    s = (await db.execute(
        select(Service).where(Service.id == service_id, Service.tenant_id == tenant_id)
    )).scalar_one_or_none()
    if not s:
        raise HTTPException(404, "Service not found")
    return {
        "id": s.id, "name": s.name, "slug": s.slug, "description": s.description,
        "tier": _enum(s.tier), "health": _enum(s.health), "owning_squad": s.owning_squad,
        "repo_url": s.repo_url, "slo_target": s.slo_availability_target,
        "slo_actual": s.slo_availability_actual,
        "error_budget_remaining_pct": s.error_budget_remaining_pct,
        "deploys_last_30d": s.deploys_last_30d, "open_incidents": s.open_incidents,
    }


@router.get("/engineers")
async def list_engineers(
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    engineers = (await db.execute(
        select(Engineer).where(Engineer.tenant_id == tenant_id).order_by(Engineer.name).limit(200)
    )).scalars().all()
    return [{
        "id": e.id, "name": e.name, "email": e.email, "github_handle": e.github_handle,
        "squad": e.squad, "seniority": e.seniority, "on_call": e.on_call,
        "review_load": e.review_load, "hr_employee_id": e.hr_employee_id,
    } for e in engineers]


# ── Pull requests ─────────────────────────────────────────────────────────────

@router.get("/pull-requests")
async def list_pull_requests(
    tenant_id: str = Depends(get_tenant_id),
    status: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    q = select(PullRequest).where(PullRequest.tenant_id == tenant_id)
    if status:
        q = q.where(PullRequest.status == status)
    prs = (await db.execute(q.order_by(PullRequest.opened_at.desc()).limit(200))).scalars().all()
    return [{
        "id": p.id, "number": p.number, "title": p.title, "status": _enum(p.status),
        "branch": p.branch, "service_id": p.service_id, "author_id": p.author_id,
        "additions": p.additions, "deletions": p.deletions, "files_changed": p.files_changed,
        "touches_migrations": p.touches_migrations, "touches_auth": p.touches_auth,
        "test_coverage_delta": p.test_coverage_delta, "ci_passing": p.ci_passing,
        "approvals": p.approvals,
        "ai_risk_level": _enum(p.ai_risk_level), "ai_summary": p.ai_summary,
        "ai_findings": p.ai_findings or [],
        "opened_at": p.opened_at.isoformat() if p.opened_at else None,
    } for p in prs]


@router.post("/pull-requests/{pr_id}/review")
async def review_pull_request(
    pr_id: str,
    tenant: dict = Depends(require_role("operator")),
    db: AsyncSession = Depends(get_db),
):
    """Gated AI code review — writes risk + findings back onto the PR."""
    tenant_id = tenant["tenant_id"]
    try:
        result = await CodeReviewAgent().review_pull_request(db, pr_id, tenant_id)
        await record_security_event(
            tenant_id=tenant_id, event_type="MODIFICATION", action="EXECUTE",
            actor=tenant.get("name"), actor_role=tenant.get("role"),
            resource_type="pull_request", resource_id=pr_id,
        )
        return result
    except ValueError as e:
        raise HTTPException(404, detail=str(e))
    except Exception as e:
        logger.exception("%s failed", __name__)
        raise HTTPException(500, detail="Internal error - see server logs") from e


# ── Deployments ───────────────────────────────────────────────────────────────

@router.get("/deployments")
async def list_deployments(
    tenant_id: str = Depends(get_tenant_id),
    environment: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    q = select(Deployment).where(Deployment.tenant_id == tenant_id)
    if environment:
        q = q.where(Deployment.environment == environment)
    deploys = (await db.execute(q.order_by(Deployment.started_at.desc()).limit(200))).scalars().all()
    return [{
        "id": d.id, "version": d.version, "environment": d.environment,
        "status": _enum(d.status), "service_id": d.service_id,
        "deployed_by": d.deployed_by, "change_count": d.change_count,
        "is_rollback": d.is_rollback,
        "ai_risk_level": _enum(d.ai_risk_level), "ai_risk_score": d.ai_risk_score,
        "ai_rationale": d.ai_rationale,
        "started_at": d.started_at.isoformat() if d.started_at else None,
        "duration_seconds": d.duration_seconds,
    } for d in deploys]


@router.post("/deployments/{deployment_id}/assess")
async def assess_deployment(
    deployment_id: str,
    tenant: dict = Depends(require_role("operator")),
    db: AsyncSession = Depends(get_db),
):
    """Gated deploy-risk assessment. Always routes to human approval."""
    tenant_id = tenant["tenant_id"]
    try:
        result = await DeployRiskAgent().assess_deployment(db, deployment_id, tenant_id)
        await record_security_event(
            tenant_id=tenant_id, event_type="MODIFICATION", action="EXECUTE",
            actor=tenant.get("name"), actor_role=tenant.get("role"),
            resource_type="deployment", resource_id=deployment_id,
        )
        return result
    except ValueError as e:
        raise HTTPException(404, detail=str(e))
    except Exception as e:
        logger.exception("%s failed", __name__)
        raise HTTPException(500, detail="Internal error - see server logs") from e


# ── Incidents ─────────────────────────────────────────────────────────────────

@router.get("/incidents")
async def list_incidents(
    tenant_id: str = Depends(get_tenant_id),
    status: Optional[str] = None,
    severity: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    q = select(Incident).where(Incident.tenant_id == tenant_id)
    if status:
        q = q.where(Incident.status == status)
    if severity:
        q = q.where(Incident.severity == severity)
    incidents = (await db.execute(q.order_by(Incident.detected_at.desc()).limit(200))).scalars().all()
    return [{
        "id": i.id, "number": i.incident_number, "title": i.title,
        "description": i.description, "severity": _enum(i.severity), "status": _enum(i.status),
        "service_id": i.service_id, "commander_id": i.commander_id,
        "customer_impacting": i.customer_impacting, "affected_users": i.affected_users,
        "detected_by": i.detected_by,
        "ai_severity_assessment": i.ai_severity_assessment,
        "ai_probable_cause": i.ai_probable_cause,
        "ai_recommended_action": i.ai_recommended_action,
        "detected_at": i.detected_at.isoformat() if i.detected_at else None,
        "time_to_acknowledge_mins": i.time_to_acknowledge_mins,
        "time_to_resolve_mins": i.time_to_resolve_mins,
    } for i in incidents]


@router.get("/incidents/{incident_id}")
async def get_incident(
    incident_id: str,
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    i = (await db.execute(
        select(Incident).where(Incident.id == incident_id, Incident.tenant_id == tenant_id)
    )).scalar_one_or_none()
    if not i:
        raise HTTPException(404, "Incident not found")
    return {
        "id": i.id, "number": i.incident_number, "title": i.title, "description": i.description,
        "severity": _enum(i.severity), "status": _enum(i.status), "service_id": i.service_id,
        "customer_impacting": i.customer_impacting, "affected_users": i.affected_users,
        "ai_probable_cause": i.ai_probable_cause,
        "ai_recommended_action": i.ai_recommended_action,
        "suspected_deployment_id": i.suspected_deployment_id,
        "detected_at": i.detected_at.isoformat() if i.detected_at else None,
    }


@router.post("/incidents/{incident_id}/triage")
async def triage_incident(
    incident_id: str,
    tenant: dict = Depends(require_role("operator")),
    db: AsyncSession = Depends(get_db),
):
    """Gated AI incident triage — severity, probable cause, recommended action."""
    tenant_id = tenant["tenant_id"]
    try:
        result = await IncidentAgent().triage_incident(db, incident_id, tenant_id)
        await record_security_event(
            tenant_id=tenant_id, event_type="MODIFICATION", action="EXECUTE",
            actor=tenant.get("name"), actor_role=tenant.get("role"),
            resource_type="incident", resource_id=incident_id,
        )
        return result
    except ValueError as e:
        raise HTTPException(404, detail=str(e))
    except Exception as e:
        logger.exception("%s failed", __name__)
        raise HTTPException(500, detail="Internal error - see server logs") from e


@router.get("/postmortems")
async def list_postmortems(
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    pms = (await db.execute(
        select(Postmortem).where(Postmortem.tenant_id == tenant_id)
        .order_by(Postmortem.created_at.desc()).limit(200)
    )).scalars().all()
    return [{
        "id": p.id, "incident_id": p.incident_id, "summary": p.summary,
        "root_cause": p.root_cause,
        "contributing_factors": p.contributing_factors or [],
        "action_items": p.action_items or [],
        "published": p.published,
        "created_at": p.created_at.isoformat() if p.created_at else None,
    } for p in pms]
