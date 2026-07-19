"""KAEOS — Brain Overview API (Enterprise Intelligence Summary)"""
import logging

from app.core.tenant import get_tenant_id
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func as sqlfunc
from datetime import datetime, timezone, timedelta

from app.core.database import get_db
from app.models.domain import (
    Rule, Skill, SkillExecution, Workflow, Signal,
)
from app.models.agent_factory import DeployedAgent, AgentStatus

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/brain", tags=["Brain — Enterprise Overview"])


@router.get("/overview")
async def brain_overview(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    """
    Enterprise Brain overview — single aggregated snapshot.
    Powers the Overview page. Every value is computed from DB.
    """
    now = datetime.now(timezone.utc)

    # Every aggregate below is scoped to the caller's tenant.
    # ── Total counts ──
    rules_result = await db.execute(
        select(sqlfunc.count(Rule.id)).where(Rule.tenant_id == tenant_id, Rule.is_archived == False)
    )
    total_rules = rules_result.scalar() or 0

    exec_rules_result = await db.execute(
        select(sqlfunc.count(Rule.id)).where(
            Rule.tenant_id == tenant_id, Rule.is_archived == False, Rule.is_executable == True
        )
    )
    executable_rules = exec_rules_result.scalar() or 0

    skills_result = await db.execute(
        select(sqlfunc.count(Skill.id)).where(Skill.tenant_id == tenant_id)
    )
    total_skills = skills_result.scalar() or 0

    executions_result = await db.execute(
        select(sqlfunc.count(SkillExecution.id)).where(SkillExecution.tenant_id == tenant_id)
    )
    total_executions = executions_result.scalar() or 0

    # ── Department count (distinct domains) ──
    dept_result = await db.execute(
        select(sqlfunc.count(sqlfunc.distinct(Rule.domain))).where(
            Rule.tenant_id == tenant_id, Rule.is_archived == False, Rule.domain.isnot(None)
        )
    )
    departments = dept_result.scalar() or 0

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

    # ── Average confidence ──
    avg_conf_result = await db.execute(
        select(sqlfunc.avg(Rule.confidence_scalar)).where(
            Rule.tenant_id == tenant_id, Rule.is_archived == False
        )
    )
    avg_confidence = round(avg_conf_result.scalar() or 0.0, 4)

    # ── Freshness ratio ──
    within_hl = 0
    decaying = 0
    expired = 0
    all_exec_rules = await db.execute(
        select(Rule).where(
            Rule.tenant_id == tenant_id, Rule.is_archived == False, Rule.is_executable == True
        )
    )
    for r in all_exec_rules.scalars().all():
        val_date = r.validated_at or r.created_at
        if val_date:
            days = (now - val_date.replace(tzinfo=timezone.utc)).days
            ratio = days / max(r.half_life_days, 1)
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

    # ── Success rate ──
    week_ago = now - timedelta(days=7)
    exec_7d = await db.execute(
        select(sqlfunc.count(SkillExecution.id)).where(
            SkillExecution.tenant_id == tenant_id,
            SkillExecution.started_at >= week_ago
        )
    )
    total_7d = exec_7d.scalar() or 0
    success_7d = await db.execute(
        select(sqlfunc.count(SkillExecution.id)).where(
            SkillExecution.tenant_id == tenant_id,
            SkillExecution.started_at >= week_ago,
            SkillExecution.status == "SUCCESS_CLEAN",
        )
    )
    success_count = success_7d.scalar() or 0
    success_rate = round(success_count / max(total_7d, 1), 4)

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
