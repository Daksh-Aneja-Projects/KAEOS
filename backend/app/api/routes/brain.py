"""KAEOS — Brain Overview API (Enterprise Intelligence Summary)"""
import logging

from app.core.tenant import get_tenant_id, require_role
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func as sqlfunc
from datetime import datetime, timezone, timedelta

from app.core.database import get_db
from app.models.domain import (
    Rule, Skill, SkillExecution, Workflow, Signal,
)
from app.models.agent_factory import DeployedAgent, AgentStatus
from app.models.execution_status import ExecutionStatus

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/brain", tags=["Brain — Enterprise Overview"])

# Separate prefix, same file: the knowledge/semantic-index surface has no
# dedicated routes module and this file owns the brain/knowledge domain.
knowledge_router = APIRouter(prefix="/knowledge", tags=["Knowledge - Semantic Index"])


@knowledge_router.post("/skill-embeddings/backfill")
async def backfill_skill_embeddings_route(
    tenant: dict = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """Embed this tenant's ACTIVE skills that have no embedding row yet.

    Idempotent admin maintenance action. Uses the tenant's own model router;
    when only simulated embeddings are available nothing is persisted and the
    response reports embeddings_simulated=true.
    """
    from app.services.knowledge import backfill_skill_embeddings

    return await backfill_skill_embeddings(db, tenant["tenant_id"])


@router.get("/overview")
async def brain_overview(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    """
    Enterprise Brain overview — single aggregated snapshot.
    Powers the Overview page. Every value is computed from DB.
    """
    now = datetime.now(timezone.utc)

    # Every aggregate below is scoped to the caller's tenant.
    # ── Rule aggregates: one round trip, not four. COUNT(DISTINCT domain)
    # ignores NULL domains, matching the old explicit isnot(None) filter. ──
    total_rules, executable_rules, departments, raw_avg_conf = (await db.execute(
        select(
            sqlfunc.count(Rule.id),
            sqlfunc.count(Rule.id).filter(Rule.is_executable == True),
            sqlfunc.count(sqlfunc.distinct(Rule.domain)),
            sqlfunc.avg(Rule.confidence_scalar),
        ).where(Rule.tenant_id == tenant_id, Rule.is_archived == False)
    )).one()
    total_rules = total_rules or 0
    executable_rules = executable_rules or 0
    departments = departments or 0

    skills_result = await db.execute(
        select(sqlfunc.count(Skill.id)).where(Skill.tenant_id == tenant_id)
    )
    total_skills = skills_result.scalar() or 0

    # ── Execution aggregates: total, last-7d, last-7d success in ONE scan ──
    week_ago = now - timedelta(days=7)
    total_executions, total_7d, success_count = (await db.execute(
        select(
            sqlfunc.count(SkillExecution.id),
            sqlfunc.count(SkillExecution.id).filter(SkillExecution.started_at >= week_ago),
            sqlfunc.count(SkillExecution.id).filter(
                SkillExecution.started_at >= week_ago,
                SkillExecution.status == ExecutionStatus.SUCCESS_CLEAN),
        ).where(SkillExecution.tenant_id == tenant_id)
    )).one()
    total_executions = total_executions or 0

    # ── Processes count (workflows) ──
    workflow_result = await db.execute(
        select(sqlfunc.count(Workflow.id)).where(Workflow.tenant_id == tenant_id)
    )
    processes = workflow_result.scalar() or 0

    # ── Workforces count (deployed agents) ──
    try:
        workforce_result = await db.execute(
            select(sqlfunc.count(DeployedAgent.id)).where(
                DeployedAgent.tenant_id == tenant_id,
                DeployedAgent.status == AgentStatus.RUNNING
            )
        )
        workforces = workforce_result.scalar() or 0
    except Exception as exc:
        # Graceful degradation: still return the rest of the snapshot, but make a
        # schema/DB fault visible rather than silently reporting an empty tenant.
        logger.warning(
            "brain_overview: deployed-agent count failed for tenant %s (reporting 0): %s",
            tenant_id, exc, exc_info=True,
        )
        workforces = 0

    # ── Knowledge coverage ──
    knowledge_coverage = round(executable_rules / max(total_rules, 1), 4)

    # ── Average confidence (from the merged Rule aggregate above) ──
    avg_confidence = round(float(raw_avg_conf or 0.0), 4)

    # ── Freshness ratio: three thin columns, not 200 full Rule rows ──
    within_hl = 0
    decaying = 0
    expired = 0
    all_exec_rules = await db.execute(
        select(Rule.validated_at, Rule.created_at, Rule.half_life_days).where(
            Rule.tenant_id == tenant_id, Rule.is_archived == False, Rule.is_executable == True
        )
        .order_by(Rule.validated_at.desc())
        .limit(200)
    )
    for validated_at, created_at, half_life_days in all_exec_rules.all():
        val_date = validated_at or created_at
        if val_date:
            days = (now - val_date.replace(tzinfo=timezone.utc)).days
            ratio = days / max(half_life_days, 1)
            if ratio < 0.5:
                within_hl += 1
            elif ratio < 1.0:
                decaying += 1
            else:
                expired += 1
        else:
            expired += 1
    fresh_total = max(within_hl + decaying + expired, 1)
    freshness_ratio = round(within_hl / fresh_total, 4)

    # ── Success rate (from the merged execution aggregate above) ──
    success_rate = round((success_count or 0) / max(total_7d or 0, 1), 4)

    # ── Enterprise IQ ──
    # Same formula as /dashboard/health overall_score
    coverage_avg_result = await db.execute(
        select(
            Rule.domain,
            sqlfunc.count(Rule.id),
        )
        .where(Rule.tenant_id == tenant_id, Rule.is_archived == False)
        .group_by(Rule.domain)
    )
    dept_rows = coverage_avg_result.all()
    coverage_scores = []
    for domain, count in dept_rows:
        if not domain:
            continue
        coverage_scores.append(min(1.0, count / 20.0))
    coverage_avg = sum(coverage_scores) / max(len(coverage_scores), 1)

    enterprise_iq = int(
        (avg_confidence * 40) + (coverage_avg * 30) +
        (freshness_ratio * 20) + (success_rate * 10)
    )
    enterprise_iq = min(enterprise_iq, 100)

    # ── Signals count ──
    signals_result = await db.execute(
        select(sqlfunc.count(Signal.id)).where(Signal.tenant_id == tenant_id)
    )
    total_signals = signals_result.scalar() or 0

    return {
        "enterprise_iq": enterprise_iq,
        "knowledge_coverage": knowledge_coverage,
        "avg_confidence": avg_confidence,
        "freshness_ratio": freshness_ratio,
        "success_rate": success_rate,
        "departments": departments,
        "processes": processes,
        "workforces": workforces,
        "total_rules": total_rules,
        "executable_rules": executable_rules,
        "total_skills": total_skills,
        "total_executions": total_executions,
        "total_signals": total_signals,
    }


# ── Company Brain: self-proposed, human-governed missions ────────────────────
# The brain writes PENDING proposals on a cadence (or on demand via /reflect); an
# operator approves one to spawn a governed mission (still through the 7 gates) or
# rejects it, which the brain remembers as a 'no'. A proposal never self-executes.
from typing import Optional  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from pydantic import BaseModel  # noqa: E402
from app.core.audit import record_security_event  # noqa: E402
from app.core.tenant import approver_identity  # noqa: E402
from app.models.brain import BrainProposal  # noqa: E402
from app.services import company_brain  # noqa: E402


def _proposal_view(p: BrainProposal) -> dict:
    return {
        "id": p.id, "title": p.title, "goal": p.goal, "rationale": p.rationale,
        "evidence": p.evidence or [], "signal_kind": p.signal_kind,
        "priority": p.priority, "status": p.status, "mission_id": p.mission_id,
        "outcome": p.outcome,
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "decided_at": p.decided_at.isoformat() if p.decided_at else None,
        "decided_by": p.decided_by,
    }


@router.get("/proposals")
async def list_proposals(
    status: Optional[str] = None,
    limit: int = 50,
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """The brain's proposals for this tenant, newest first. Filter by status
    (PENDING to see what awaits a decision)."""
    q = select(BrainProposal).where(BrainProposal.tenant_id == tenant_id)
    if status:
        q = q.where(BrainProposal.status == status.strip().upper())
    q = q.order_by(BrainProposal.created_at.desc()).limit(max(1, min(200, limit)))
    rows = (await db.execute(q)).scalars().all()
    return {"proposals": [_proposal_view(p) for p in rows], "count": len(rows)}


@router.post("/reflect")
async def reflect_now(
    tenant: dict = Depends(require_role("operator")),
    db: AsyncSession = Depends(get_db),
):
    """Run a reflection cycle now: observe reality, propose missions. On-demand
    twin of the scheduled brain job. Proposals are PENDING — nothing executes."""
    receipt = await company_brain.reflect_and_propose(db, tenant["tenant_id"])
    await record_security_event(
        tenant_id=tenant["tenant_id"], event_type="BRAIN_REFLECT", action="WRITE",
        actor=approver_identity(tenant), actor_role=tenant.get("role"),
        resource_type="brain_proposal", resource_id=None,
        details={"observed": receipt.get("observed"), "proposed": receipt.get("proposed")},
    )
    return receipt


@router.post("/proposals/{proposal_id}/approve")
async def approve_proposal_route(
    proposal_id: str,
    tenant: dict = Depends(require_role("operator")),
    db: AsyncSession = Depends(get_db),
):
    """Approve a proposal: plan a governed mission from its goal and link it back.
    Every step of that mission still passes the 7 gates."""
    try:
        result = await company_brain.approve_proposal(
            db, tenant["tenant_id"], proposal_id, approver_identity(tenant))
    except ValueError as e:
        raise HTTPException(status_code=404 if "not found" in str(e) else 409, detail=str(e))
    await record_security_event(
        tenant_id=tenant["tenant_id"], event_type="BRAIN_APPROVE", action="WRITE",
        actor=approver_identity(tenant), actor_role=tenant.get("role"),
        resource_type="brain_proposal", resource_id=proposal_id,
        details={"mission_id": result.get("mission_id")},
    )
    return result


class _RejectIn(BaseModel):
    reason: Optional[str] = None


@router.post("/proposals/{proposal_id}/reject")
async def reject_proposal_route(
    proposal_id: str,
    body: _RejectIn = _RejectIn(),
    tenant: dict = Depends(require_role("operator")),
    db: AsyncSession = Depends(get_db),
):
    """Reject a proposal. The brain suppresses the same idea for a cooldown."""
    try:
        result = await company_brain.reject_proposal(
            db, tenant["tenant_id"], proposal_id, approver_identity(tenant), body.reason)
    except ValueError as e:
        raise HTTPException(status_code=404 if "not found" in str(e) else 409, detail=str(e))
    await record_security_event(
        tenant_id=tenant["tenant_id"], event_type="BRAIN_REJECT", action="WRITE",
        actor=approver_identity(tenant), actor_role=tenant.get("role"),
        resource_type="brain_proposal", resource_id=proposal_id,
        details={"reason": (body.reason or "")[:200]},
    )
    return result
