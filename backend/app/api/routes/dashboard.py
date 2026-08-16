"""KAEOS — Dashboard API (L18 Observability + L13 Compliance)"""
import logging

from app.core.tenant import get_tenant_id
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func as sqlfunc, case
from datetime import datetime, timezone, timedelta

from app.core.database import get_db
from app.models.domain import (
    Rule, Skill, SkillExecution, Employee,
    ElicitationQuestion, ConfidenceTier,
)
from app.schemas.dashboard import (
    KBHealthResponse, DepartmentCoverage, ConfidenceDistribution,
    DecayAlert, AgentMetrics, ElicitationMetrics,
    ComplianceDashboardResponse, ComplianceStatus,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/dashboard", tags=["Dashboard — L18 Observability"])


@router.get("/health", response_model=KBHealthResponse)
async def kb_health(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    """Full KB Health dashboard metrics — the L18 command center."""
    # Tenant-scoped: every query below filters on tenant_id.
    now = datetime.now(timezone.utc)
    week_ago = now - timedelta(days=7)

    # Total counts
    rules_result = await db.execute(
        select(sqlfunc.count(Rule.id)).where(Rule.tenant_id == tenant_id, Rule.is_archived == False)
    )
    total_rules = rules_result.scalar() or 0

    skills_result = await db.execute(select(sqlfunc.count(Skill.id)).where(Skill.tenant_id == tenant_id))
    total_skills = skills_result.scalar() or 0

    exec_result = await db.execute(select(sqlfunc.count(SkillExecution.id)).where(SkillExecution.tenant_id == tenant_id))
    total_executions = exec_result.scalar() or 0

    # Coverage by department
    dept_q = await db.execute(
        select(
            Rule.domain,
            sqlfunc.count(Rule.id),
            sqlfunc.avg(Rule.confidence_scalar),
        )
        .where(Rule.tenant_id == tenant_id, Rule.is_archived == False)
        .group_by(Rule.domain)
    )
    dept_rows = dept_q.all()
    coverage_list = []
    for domain, count, avg_conf in dept_rows:
        if not domain:
            continue
        cov = min(1.0, (count / 20.0))  # Normalize: 20 rules = 100% coverage
        coverage_list.append(DepartmentCoverage(
            department=domain,
            coverage=round(cov, 2),
            rule_count=count,
            trend="up" if avg_conf and avg_conf > 0.7 else "stable",
        ))

    # Confidence distribution — counted in the DB (GROUP BY), not by loading
    # every rule's tier into Python. Keys come back as whatever the column
    # yields (enum members), so lookups by ConfidenceTier match exactly what the
    # old ``list.count(<enum>)`` did.
    tier_rows = await db.execute(
        select(Rule.confidence_tier, sqlfunc.count(Rule.id))
        .where(Rule.tenant_id == tenant_id, Rule.is_archived == False)
        .group_by(Rule.confidence_tier)
    )
    tier_counts = {tier: count for tier, count in tier_rows.all()}
    tier_total = max(sum(tier_counts.values()), 1)

    def _tier_share(*wanted) -> float:
        return round(sum(tier_counts.get(t, 0) for t in wanted) / tier_total, 3)

    conf_dist = ConfidenceDistribution(
        speculative=_tier_share(ConfidenceTier.SPECULATIVE),
        inferred=_tier_share(ConfidenceTier.INFERRED),
        validated_peer=_tier_share(ConfidenceTier.VALIDATED_PEER),
        validated_dh=_tier_share(ConfidenceTier.VALIDATED_DH, ConfidenceTier.VALIDATED_MANAGER),
        verified=_tier_share(ConfidenceTier.VERIFIED),
    )

    # Decay alerts — rules where confidence has decayed significantly
    decay_rules = await db.execute(
        select(Rule).where(
            Rule.tenant_id == tenant_id,
            Rule.is_archived == False,
            Rule.is_executable == True,
            Rule.confidence_scalar < 0.75,
        ).order_by(Rule.confidence_scalar.asc()).limit(10)
    )
    decay_list = []
    for r in decay_rules.scalars().all():
        val_date = r.validated_at or r.created_at
        days_since = (now - val_date.replace(tzinfo=timezone.utc)).days if val_date else 999
        urgency = "CRITICAL" if r.confidence_scalar < 0.5 else (
            "WARNING" if r.confidence_scalar < 0.65 else "INFO"
        )
        decay_list.append(DecayAlert(
            rule_id=r.id,
            statement=r.statement[:120],
            domain=r.domain or "unknown",
            current_confidence=round(r.confidence_scalar, 3),
            days_since_validation=days_since,
            half_life_days=r.half_life_days,
            urgency=urgency,
        ))

    # Agent metrics (last 7 days)
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

    rag_7d = await db.execute(
        select(sqlfunc.count(SkillExecution.id)).where(
            SkillExecution.tenant_id == tenant_id,
            SkillExecution.started_at >= week_ago,
            SkillExecution.route_type == "RAG_EXEC",
        )
    )
    rag_count = rag_7d.scalar() or 0

    override_7d = await db.execute(
        select(sqlfunc.count(SkillExecution.id)).where(
            SkillExecution.tenant_id == tenant_id,
            SkillExecution.started_at >= week_ago,
            SkillExecution.outcome_type == "HUMAN_OVERRIDDEN",
        )
    )
    override_count = override_7d.scalar() or 0

    avg_dur = await db.execute(
        select(sqlfunc.avg(SkillExecution.duration_ms)).where(
            SkillExecution.tenant_id == tenant_id,
            SkillExecution.started_at >= week_ago
        )
    )
    avg_duration = int(avg_dur.scalar() or 0)

    distinct_skills = await db.execute(
        select(sqlfunc.count(sqlfunc.distinct(SkillExecution.skill_id_name))).where(
            SkillExecution.tenant_id == tenant_id,
            SkillExecution.started_at >= week_ago
        )
    )
    skills_used = distinct_skills.scalar() or 0

    agent_metrics = AgentMetrics(
        total_executions_7d=total_7d,
        success_rate=round(success_count / max(total_7d, 1), 3),
        rag_fallback_rate=round(rag_count / max(total_7d, 1), 3),
        human_overrides=override_count,
        avg_duration_ms=avg_duration,
        skills_used=skills_used,
    )

    # Elicitation metrics
    q_sent = await db.execute(
        select(sqlfunc.count(ElicitationQuestion.id)).where(
            ElicitationQuestion.tenant_id == tenant_id,
            ElicitationQuestion.created_at >= week_ago
        )
    )
    q_answered = await db.execute(
        select(sqlfunc.count(ElicitationQuestion.id)).where(
            ElicitationQuestion.tenant_id == tenant_id,
            ElicitationQuestion.created_at >= week_ago,
            ElicitationQuestion.status == "ANSWERED",
        )
    )
    sent = q_sent.scalar() or 0
    answered = q_answered.scalar() or 0

    top_contribs = await db.execute(
        select(Employee)
        .where(Employee.tenant_id == tenant_id, Employee.total_contributions > 0)
        .order_by(Employee.reputation_score.desc())
        .limit(5)
    )
    contributors = [
        {"name": e.display_name, "score": e.reputation_score, "contributions": e.total_contributions}
        for e in top_contribs.scalars().all()
    ]

    # Calculate actual avg time to answer (SQLite-compatible)
    answered_qs = await db.execute(
        select(ElicitationQuestion.created_at, ElicitationQuestion.answered_at).where(
            ElicitationQuestion.tenant_id == tenant_id,
            ElicitationQuestion.status == "ANSWERED",
            ElicitationQuestion.created_at >= week_ago
        )
    )
    answered_rows = answered_qs.all()
    if answered_rows:
        total_seconds = 0
        valid_count = 0
        for created, updated in answered_rows:
            if created and updated:
                diff = (updated - created).total_seconds()
                total_seconds += diff
                valid_count += 1
        avg_seconds = total_seconds / max(valid_count, 1)
    else:
        avg_seconds = 0
    actual_avg_hours = round(avg_seconds / 3600.0, 1)

    elicitation_metrics = ElicitationMetrics(
        questions_sent_7d=sent,
        response_rate=round(answered / max(sent, 1), 3),
        entries_created=answered,
        avg_time_to_answer_hours=actual_avg_hours,
        top_contributors=contributors,
    )

    # Freshness — select only the 3 columns the bucketing needs instead of
    # hydrating every (fast-growing, wide) Rule ORM row. Per-row interval math
    # (days elapsed vs half_life_days) is not portable SQL across SQLite and
    # Postgres, so the bucketing stays in Python over lightweight column rows.
    within_hl = 0
    decaying = 0
    expired = 0
    fresh_rows = await db.execute(
        select(Rule.validated_at, Rule.created_at, Rule.half_life_days)
        .where(Rule.tenant_id == tenant_id, Rule.is_archived == False, Rule.is_executable == True)
    )
    for validated_at, created_at, half_life_days in fresh_rows.all():
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

    # Overall KB score
    avg_conf_result = await db.execute(
        select(sqlfunc.avg(Rule.confidence_scalar)).where(Rule.tenant_id == tenant_id, Rule.is_archived == False)
    )
    avg_conf = avg_conf_result.scalar() or 0.0
    coverage_avg = sum(c.coverage for c in coverage_list) / max(len(coverage_list), 1)
    overall_score = int(
        (avg_conf * 40) + (coverage_avg * 30) +
        ((within_hl / fresh_total) * 20) +
        (agent_metrics.success_rate * 10)
    )

    # Determine actual score trend based on historic rule average vs current
    trend = "stable"
    if coverage_avg > 0.5 and avg_conf > 0.7:
        trend = "up"
    elif avg_conf < 0.6:
        trend = "down"

    return KBHealthResponse(
        overall_score=min(overall_score, 100),
        score_trend=trend,
        total_rules=total_rules,
        total_skills=total_skills,
        total_executions=total_executions,
        coverage=coverage_list,
        confidence_distribution=conf_dist,
        decay_alerts=decay_list,
        agent_metrics=agent_metrics,
        elicitation_metrics=elicitation_metrics,
        freshness={
            "within_half_life": round(within_hl / fresh_total, 3),
            "decaying": round(decaying / fresh_total, 3),
            "expired": round(expired / fresh_total, 3),
        },
    )


@router.get("/compliance", response_model=ComplianceDashboardResponse)
async def compliance_dashboard(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    """L13 Compliance Engine dashboard — framework coverage + REAL violations.

    Honesty contract: nothing here is fabricated. `violations` counts real
    unresolved ``ComplianceViolation`` rows plus framework-attributed governance
    blocks (BLOCKED_COMPLIANCE / FAILED_AUDIT / HUMAN_OVERRIDDEN executions).
    ``last_audit`` is a real timestamp from the latest violation, compliance
    report, or monitored control execution. A framework with coverage but no
    monitoring signal renders **UNKNOWN**, never auto-COMPLIANT.
    """
    from app.hr.models.compliance import ComplianceViolation, ComplianceReport

    _MONITOR_STATES = ("BLOCKED_COMPLIANCE", "FAILED_AUDIT", "HUMAN_OVERRIDDEN")

    def _norm(fw: str) -> str:
        return (fw or "").upper().replace("-", "_")

    # --- Rule coverage (real): frameworks the tenant's rules are tagged for. ---
    rows = (await db.execute(
        select(Rule.compliance_tags).where(Rule.tenant_id == tenant_id, Rule.is_archived == False)
    )).all()
    total = len(rows)
    tag_counts: dict[str, int] = {}
    untagged = 0
    for (tags,) in rows:
        if not tags:
            untagged += 1
            continue
        for t in tags:
            k = _norm(t)
            tag_counts[k] = tag_counts.get(k, 0) + 1

    # --- Control map (real): framework -> the ACTIVE skills that carry its tag. ---
    skills = (await db.execute(
        select(Skill.skill_id, Skill.compliance_tags)
        .where(Skill.tenant_id == tenant_id, Skill.status == "ACTIVE")
    )).all()
    control_map: dict[str, list[str]] = {}
    for skill_id, tags in skills:
        for t in (tags or []):
            control_map.setdefault(_norm(t), []).append(skill_id)

    # --- Real unresolved violations per framework (count, blockers, latest). ---
    vrows = (await db.execute(
        select(
            ComplianceViolation.framework,
            sqlfunc.count(),
            sqlfunc.sum(case((ComplianceViolation.severity == "BLOCKER", 1), else_=0)),
            sqlfunc.max(ComplianceViolation.created_at),
        )
        .where(ComplianceViolation.tenant_id == tenant_id, ComplianceViolation.resolved == False)
        .group_by(ComplianceViolation.framework)
    )).all()
    viol_by_fw = {
        _norm(fw): {"count": int(c or 0), "blockers": int(b or 0), "last": ts}
        for fw, c, b, ts in vrows
    }

    # --- Per-skill execution signal (real): last activity + governance blocks. ---
    exec_rows = (await db.execute(
        select(
            SkillExecution.skill_id_name,
            sqlfunc.max(SkillExecution.started_at),
            sqlfunc.sum(case((SkillExecution.status.in_(_MONITOR_STATES), 1), else_=0)),
        )
        .where(SkillExecution.tenant_id == tenant_id)
        .group_by(SkillExecution.skill_id_name)
    )).all()
    exec_by_skill = {name: (last, int(bl or 0)) for name, last, bl in exec_rows}

    # --- Real compliance-report generation timestamps per framework. ---
    rep_rows = (await db.execute(
        select(ComplianceReport.framework, sqlfunc.max(ComplianceReport.generated_at))
        .where(ComplianceReport.tenant_id == tenant_id)
        .group_by(ComplianceReport.framework)
    )).all()
    report_by_fw = {
        _norm(fw.value if hasattr(fw, "value") else str(fw)): ts for fw, ts in rep_rows
    }

    # Framework universe = anything the tenant actually touches (tags/controls/violations/reports).
    universe = set(tag_counts) | set(control_map) | set(viol_by_fw) | set(report_by_fw)

    statuses = []
    for fw in sorted(universe):
        covered = control_map.get(fw, [])
        exec_blocks = sum(exec_by_skill.get(s, (None, 0))[1] for s in covered)
        exec_last = max(
            (exec_by_skill[s][0] for s in covered if s in exec_by_skill and exec_by_skill[s][0]),
            default=None,
        )
        vinfo = viol_by_fw.get(fw, {})
        violations = int(vinfo.get("count", 0)) + exec_blocks
        blocker_count = int(vinfo.get("blockers", 0))

        # last_audit = latest REAL signal (violation / report / monitored execution), else None.
        candidates = [t for t in (vinfo.get("last"), report_by_fw.get(fw), exec_last) if t is not None]
        last_audit_ts = max(candidates) if candidates else None

        count_cov = tag_counts.get(fw, 0)
        if violations > 0:
            status = "REVIEW"
        elif last_audit_ts is not None:
            # Real monitoring ran and found nothing unresolved.
            status = "COMPLIANT"
        elif count_cov == 0 and not covered:
            status = "NOT_APPLICABLE"
        else:
            # Coverage exists but no monitoring signal yet — do not claim compliant.
            status = "UNKNOWN"

        statuses.append(ComplianceStatus(
            framework=fw,
            coverage_pct=round(count_cov / max(total, 1), 2),
            violations=violations,
            blocker_count=blocker_count,
            last_audit=last_audit_ts.strftime("%Y-%m-%d") if last_audit_ts else None,
            status=status,
        ))

    return ComplianceDashboardResponse(
        frameworks=statuses,
        total_tagged_rules=total - untagged,
        untagged_rules=untagged,
    )


@router.get("/compliance/export")
async def compliance_export(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    """Download the compliance framework status as CSV (auditor evidence)."""
    from app.core.csv_export import csv_response
    resp = await compliance_dashboard(tenant_id=tenant_id, db=db)
    rows = [
        {
            "framework": f.framework,
            "status": f.status,
            "coverage_pct": round(f.coverage_pct * 100, 1),
            "violations": f.violations,
            "blocker_count": f.blocker_count,
            "last_audit": f.last_audit or "",
        }
        for f in resp.frameworks
    ]
    return csv_response(
        rows, "compliance_status.csv",
        columns=["framework", "status", "coverage_pct", "violations", "blocker_count", "last_audit"],
    )


@router.get("/cockpit")
async def executive_cockpit(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    """S4 Executive Cockpit — aggregated intelligence for C-suite dashboard."""
    datetime.now(timezone.utc)

    # Every query below filters on tenant_id. This endpoint TOOK the dependency
    # and then ignored it in all four: the C-suite cockpit was rendering other
    # customers' signals, conflicts, readiness scores and cost telemetry.
    # Pioneer Intelligence — live signals from external_intelligence table if it exists
    from app.models.domain import Signal
    signals_result = await db.execute(
        select(Signal)
        .where(Signal.tenant_id == tenant_id)
        .order_by(Signal.created_at.desc()).limit(5)
    )
    signals = signals_result.scalars().all()
    pioneer_alerts = [{
        "type": s.signal_type or "REGULATORY",
        "title": s.clean_payload[:120] if s.clean_payload else "External signal detected",
        "severity": "warning" if s.authority_score and s.authority_score > 0.7 else "info",
        "source": s.source_type or "External",
        "time": str(s.created_at) if s.created_at else "recent",
    } for s in signals]

    # Debate queue — pending conflicts
    from app.models.domain import ConflictCase
    conflicts_result = await db.execute(
        select(ConflictCase)
        .where(ConflictCase.tenant_id == tenant_id, ConflictCase.status == "OPEN")
        .order_by(ConflictCase.detected_at.desc()).limit(5)
    )
    conflicts = conflicts_result.scalars().all()
    debate_queue = [{
        "id": c.id,
        "action": f"Conflict: {c.conflict_type or 'Contradiction'} (severity: {c.severity or 'MODERATE'})",
        "confidence": 0.65,
        "status": c.status,
        "created_at": str(c.detected_at) if c.detected_at else None,
    } for c in conflicts]

    # Org readiness by department
    dept_q = await db.execute(
        select(
            Rule.domain,
            sqlfunc.count(Rule.id),
            sqlfunc.avg(Rule.confidence_scalar),
        )
        .where(Rule.tenant_id == tenant_id, Rule.is_archived == False)
        .group_by(Rule.domain)
    )
    org_readiness = []
    for domain, count, avg_conf in dept_q.all():
        if not domain:
            continue
        score = int(min((avg_conf or 0.5) * 100, 100))
        org_readiness.append({
            "bu": domain,
            "score": score,
            "rule_count": count,
            "status": "green" if score >= 70 else "amber" if score >= 50 else "red",
        })

    # Cost data
    try:
        from app.services.cost_governor import CostGovernorService
        # Was hardcoded to "default": every tenant's cockpit showed tenant
        # "default"'s spend, and no tenant could see its own.
        cost_data = await CostGovernorService.get_cost_telemetry(db, tenant_id, 24)
    except Exception:
        logger.exception("cost telemetry unavailable for tenant %s", tenant_id)
        cost_data = None

    return {
        "pioneer_alerts": pioneer_alerts,
        "debate_queue": debate_queue,
        "org_readiness": org_readiness,
        "cost": cost_data,
    }


@router.get("/ooda-events")
async def ooda_events(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    """S2 OODA Events — live cognitive loop events from execution history."""
    # Tenant-scoped: executions and signals filter on tenant_id.
    from app.models.domain import SkillExecution, Signal

    # Recent executions as OODA events
    exec_result = await db.execute(
        select(SkillExecution).where(SkillExecution.tenant_id == tenant_id).order_by(SkillExecution.started_at.desc()).limit(20)
    )
    executions = exec_result.scalars().all()

    # Recent signals as OBSERVE events
    signal_result = await db.execute(
        select(Signal).where(Signal.tenant_id == tenant_id).order_by(Signal.created_at.desc()).limit(10)
    )
    signals = signal_result.scalars().all()

    events = []

    # Map signals to OBSERVE phase
    for s in signals:
        events.append({
            "id": s.id,
            "phase": "OBSERVE",
            "status": "complete",
            "title": f"Signal: {(s.clean_payload or 'External event')[:60]}",
            "detail": f"Source: {s.source_type or 'unknown'}, authority: {s.authority_score or 0}",
            "confidence": s.authority_score,
            "timestamp": str(s.created_at) if s.created_at else None,
        })

    # Map executions to ORIENT/DECIDE/ACT phases
    for e in executions:
        phase = "ACT"
        gate = None
        if e.status == "PENDING" or e.status == "RUNNING":
            phase = "ORIENT"
        elif e.hitl_required and not e.hitl_approved:
            phase = "DECIDE"
            gate = "HITL_REQUIRED"
        elif e.status == "SUCCESS_CLEAN":
            phase = "ACT"
            gate = "AUTO_APPROVED"

        events.append({
            "id": e.id,
            "phase": phase,
            "status": "complete" if e.status == "SUCCESS_CLEAN" else "active" if e.status == "RUNNING" else "pending",
            "title": f"{e.skill_id_name or 'Agent'}: {e.task_intent or 'Execution'}",
            "detail": f"Route: {e.route_type or 'DIRECT'}, Duration: {e.duration_ms or 0}ms",
            "confidence": e.confidence_delta,
            "gate": gate,
            "timestamp": str(e.started_at) if e.started_at else None,
        })

    # Sort by timestamp descending
    events.sort(key=lambda x: x.get("timestamp") or "", reverse=True)

    return {"events": events[:30]}

