"""
KAEOS Engineering Domain — API v1

Engineering + IT Ops surface: service catalog, pull requests, deployments,
incidents, postmortems, dashboard, and the three gated AI agents.
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import case, select, func as sqlfunc
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.tenant import get_tenant_id, require_role
from app.core.audit import record_security_event
from app.engineering.agents.code_review_agent import CodeReviewAgent
from app.engineering.agents.deploy_risk_agent import DeployRiskAgent
from app.engineering.agents.incident_agent import IncidentAgent
from app.engineering.models.core import Engineer, Service
from app.engineering.models.delivery import Deployment, PullRequest
from app.engineering.models.incidents import (
    Incident, IncidentSeverity, IncidentStatus, Postmortem,
)
from app.engineering.models.ops import OnCallRotation, PipelineRun

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
    # Services: one GROUP BY on health instead of loading every row.
    svc_q = await db.execute(
        select(Service.health, sqlfunc.count())
        .where(Service.tenant_id == tenant_id)
        .group_by(Service.health)
    )
    svc_counts = {(s.value if hasattr(s, "value") else str(s)): int(c) for s, c in svc_q.all()}
    total_services = sum(svc_counts.values())

    # PRs: GROUP BY status, carrying the awaiting-review count as a conditional
    # sum per status (same shape as app/engineering/services/analytics.py).
    pr_q = await db.execute(
        select(PullRequest.status, sqlfunc.count(),
               sqlfunc.coalesce(sqlfunc.sum(case(
                   (sqlfunc.coalesce(PullRequest.approvals, 0) == 0, 1), else_=0)), 0))
        .where(PullRequest.tenant_id == tenant_id)
        .group_by(PullRequest.status)
    )
    pr_counts, unreviewed_counts = {}, {}
    for s, c, unreviewed in pr_q.all():
        key = s.value if hasattr(s, "value") else str(s)
        pr_counts[key] = int(c)
        unreviewed_counts[key] = int(unreviewed or 0)
    _open_pr_states = ("OPEN", "IN_REVIEW", "CHANGES_REQUESTED")
    open_prs = sum(pr_counts.get(s, 0) for s in _open_pr_states)
    prs_awaiting_review = sum(unreviewed_counts.get(s, 0) for s in _open_pr_states)

    # Deployments: GROUP BY status; the failure rate derives from the counts.
    dep_q = await db.execute(
        select(Deployment.status, sqlfunc.count())
        .where(Deployment.tenant_id == tenant_id)
        .group_by(Deployment.status)
    )
    dep_counts = {(s.value if hasattr(s, "value") else str(s)): int(c) for s, c in dep_q.all()}
    deployments_total = sum(dep_counts.values())
    failed = dep_counts.get("FAILED", 0) + dep_counts.get("ROLLED_BACK", 0)
    change_fail_rate = (
        round(failed / deployments_total * 100, 1) if deployments_total else None
    )

    # Incidents: one pass of conditional sums plus the resolve-time average
    # (SQL AVG skips NULLs, matching the old resolved-rows-only mean).
    _closed = [IncidentStatus.RESOLVED, IncidentStatus.CLOSED]
    inc_q = await db.execute(
        select(
            sqlfunc.coalesce(sqlfunc.sum(case(
                (Incident.status.notin_(_closed), 1), else_=0)), 0),
            sqlfunc.coalesce(sqlfunc.sum(case(
                (Incident.status.notin_(_closed)
                 & (Incident.severity == IncidentSeverity.SEV1), 1), else_=0)), 0),
            sqlfunc.coalesce(sqlfunc.sum(case(
                (Incident.status == IncidentStatus.POSTMORTEM_DUE, 1), else_=0)), 0),
            sqlfunc.avg(Incident.time_to_resolve_mins),
        ).where(Incident.tenant_id == tenant_id)
    )
    open_incidents, sev1_open, postmortems_due, mttr_raw = inc_q.one()
    mttr = round(float(mttr_raw), 1) if mttr_raw is not None else None

    return {
        "total_services": total_services,
        "unhealthy_services": total_services - svc_counts.get("HEALTHY", 0),
        "open_pull_requests": open_prs,
        "prs_awaiting_review": prs_awaiting_review,
        "deployments_total": deployments_total,
        "deployments_succeeded": dep_counts.get("SUCCEEDED", 0),
        "change_failure_rate_pct": change_fail_rate,
        "open_incidents": int(open_incidents or 0),
        "sev1_open": int(sev1_open or 0),
        "mttr_minutes": mttr,
        "postmortems_due": int(postmortems_due or 0),
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


# ── On-call rotations ─────────────────────────────────────────────────────────

def _naive_utc(dt):
    """Postgres preserves tzinfo on a DateTime(timezone=True) column; SQLite
    (local dev) hands it back naive. Strip tzinfo from whichever side has it so
    the two are always comparable regardless of backend."""
    return dt.replace(tzinfo=None) if dt and dt.tzinfo else dt


def _rotation_row(r: OnCallRotation, engineers_by_id: dict) -> dict:
    eng = engineers_by_id.get(r.engineer_id)
    now = _naive_utc(datetime.now(timezone.utc))
    starts, ends = _naive_utc(r.starts_at), _naive_utc(r.ends_at)
    active = bool(starts and ends and starts <= now <= ends)
    return {
        "id": r.id, "engineer_id": r.engineer_id,
        "engineer_name": eng.name if eng else None,
        "squad": r.squad, "role": _enum(r.role), "active": active,
        "starts_at": r.starts_at.isoformat() if r.starts_at else None,
        "ends_at": r.ends_at.isoformat() if r.ends_at else None,
    }


@router.get("/oncall")
async def list_oncall_rotations(
    tenant_id: str = Depends(get_tenant_id),
    squad: Optional[str] = None,
    active_only: bool = False,
    db: AsyncSession = Depends(get_db),
):
    """On-call schedule: who is (or was, or will be) paged for each squad."""
    q = select(OnCallRotation).where(OnCallRotation.tenant_id == tenant_id)
    if squad:
        q = q.where(OnCallRotation.squad == squad)
    rotations = (await db.execute(q.order_by(OnCallRotation.starts_at.desc()).limit(200))).scalars().all()
    engineers = (await db.execute(
        select(Engineer).where(Engineer.tenant_id == tenant_id)
    )).scalars().all()
    engineers_by_id = {e.id: e for e in engineers}
    rows = [_rotation_row(r, engineers_by_id) for r in rotations]
    return [r for r in rows if r["active"]] if active_only else rows


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


# ── CI pipeline runs ─────────────────────────────────────────────────────────

@router.get("/pipeline-runs")
async def list_pipeline_runs(
    tenant_id: str = Depends(get_tenant_id),
    service_id: Optional[str] = None,
    status: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """CI build/test history - the real signal behind the deploy-risk agent's
    score, beyond a single PR's ci_passing flag."""
    q = select(PipelineRun).where(PipelineRun.tenant_id == tenant_id)
    if service_id:
        q = q.where(PipelineRun.service_id == service_id)
    if status:
        q = q.where(PipelineRun.status == status)
    runs = (await db.execute(q.order_by(PipelineRun.started_at.desc()).limit(200))).scalars().all()
    return [{
        "id": r.id, "service_id": r.service_id, "pull_request_id": r.pull_request_id,
        "pipeline_name": r.pipeline_name, "run_number": r.run_number, "status": _enum(r.status),
        "trigger": r.trigger, "branch": r.branch, "commit_sha": r.commit_sha,
        "tests_passed": r.tests_passed, "tests_failed": r.tests_failed,
        "duration_seconds": r.duration_seconds,
        "started_at": r.started_at.isoformat() if r.started_at else None,
        "completed_at": r.completed_at.isoformat() if r.completed_at else None,
    } for r in runs]


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

# ═══════════════════════════════════════════════════════════════════════
# Analytics & Workflow Layer (shared engine: app.core.workflow)
# ═══════════════════════════════════════════════════════════════════════
from app.core.workflow import (  # noqa: E402
    BulkTransitionRequest, TransitionRequest, apply_bulk_transition,
    apply_transition, list_workflow_events,
)
from app.engineering.services.analytics import engineering_analytics  # noqa: E402
from app.engineering.services.workflows import SPECS as WORKFLOW_SPECS  # noqa: E402


@router.get("/analytics")
async def get_engineering_analytics(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    """Computed incident, deploy and PR-flow KPIs for the engineering cockpit."""
    return await engineering_analytics(db, tenant_id)


@router.get("/workflows")
async def get_engineering_workflows(tenant_id: str = Depends(get_tenant_id)):
    """Declared state machines - the frontend renders incident/deploy actions from this."""
    return {name: spec.describe() for name, spec in WORKFLOW_SPECS.items()}


@router.get("/workflow-events")
async def get_engineering_workflow_events(
    entity_type: Optional[str] = None, entity_id: Optional[str] = None,
    tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db),
):
    """Tenant-scoped transition audit trail for engineering entities."""
    return await list_workflow_events(db, tenant_id, domain="engineering",
                                      entity_type=entity_type, entity_id=entity_id)


@router.post("/incidents/{incident_id}/transition")
async def transition_incident(
    incident_id: str, body: TransitionRequest,
    tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db),
):
    """Drive an incident through triage, mitigation, resolution; stamps MTTA/MTTR."""
    return await apply_transition(db, WORKFLOW_SPECS["incident"], incident_id,
                                  body.to_state, tenant, note=body.note)


@router.post("/deployments/{deployment_id}/transition")
async def transition_deployment(
    deployment_id: str, body: TransitionRequest,
    tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db),
):
    """Promote / fail / roll back a deployment through the guarded engine."""
    return await apply_transition(db, WORKFLOW_SPECS["deployment"], deployment_id,
                                  body.to_state, tenant, note=body.note)

# ═══════════════════════════════════════════════════════════════════════
# Entity Creation
# ═══════════════════════════════════════════════════════════════════════
import uuid as _uuid_mod  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402


class IncidentCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=256)
    description: Optional[str] = None
    severity: str = Field("SEV3", pattern="^SEV[1-4]$")
    service_id: Optional[str] = None
    customer_impacting: bool = False
    affected_users: Optional[int] = Field(None, ge=0)


@router.post("/incidents", status_code=201)
async def create_incident(
    body: IncidentCreate,
    tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db),
):
    """Declare an incident (starts DETECTED; drive via /transition)."""
    tenant_id = tenant["tenant_id"]
    inc = Incident(
        tenant_id=tenant_id,
        incident_number=f"INC-{_uuid_mod.uuid4().hex[:8].upper()}",
        title=body.title, description=body.description,
        severity=body.severity, service_id=body.service_id,
        customer_impacting=body.customer_impacting,
        affected_users=body.affected_users,
        detected_by="ENGINEER",
    )
    db.add(inc)
    await db.commit()
    await db.refresh(inc)
    await record_security_event(
        tenant_id=tenant_id, event_type="MODIFICATION", action="WRITE",
        actor=tenant.get("name"), actor_role=tenant.get("role"),
        resource_type="incident", resource_id=inc.id,
    )
    return {"id": inc.id, "number": inc.incident_number, "title": inc.title,
            "status": inc.status.value if hasattr(inc.status, "value") else str(inc.status),
            "severity": inc.severity.value if hasattr(inc.severity, "value") else str(inc.severity)}


@router.post("/workflows/{entity_type}/bulk-transition")
async def bulk_transition_engineering(
    entity_type: str, body: BulkTransitionRequest,
    tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db),
):
    """Apply one transition to up to 200 engineering entities; per-id outcomes."""
    spec = WORKFLOW_SPECS.get(entity_type)
    if not spec:
        raise HTTPException(404, detail=f"Unknown workflow entity '{entity_type}'. Known: {sorted(WORKFLOW_SPECS)}")
    return await apply_bulk_transition(db, spec, body.ids, body.to_state, tenant, note=body.note)
