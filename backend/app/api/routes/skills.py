"""KAEOS — Skills Registry API (L8 Compiler + L9 Runtime + L10 Feedback)"""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func as sqlfunc
from datetime import datetime, timezone
import logging
import uuid

from app.core.database import get_db
from app.core.tenant import get_tenant_id, require_role
from app.core.entitlements import require_execution_allowance
from app.core.audit import record_security_event
from app.models.domain import Skill, SkillExecution
from app.models.execution_status import PENDING_STATUSES, AgentState, ExecutionStatus
from app.services.knowledge import PolystoreEngine
from app.api.dependencies import get_polystore_engine
from app.schemas.skills import (
    SkillSummary, SkillDetail, SkillRegistryResponse,
    SkillExecutionRequest, SkillExecutionResponse,
)
from app.services.confidence import ConfidenceEngine
from app.services.lifecycle import FeedbackEngine
from app.services.compliance import ComplianceEngine
from app.services.activity_feed import ActivityFeedService
from app.models.agent_factory import ActivityEventType, ActivitySeverity
from fastapi import BackgroundTasks

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/skills", tags=["Skills — L8 Registry"])
confidence_engine = ConfidenceEngine()
feedback_engine = FeedbackEngine()
activity_feed = ActivityFeedService()
compliance_engine = ComplianceEngine()


@router.get("", response_model=SkillRegistryResponse)
async def list_skills(
    department: str | None = None,
    status: str | None = None,
    min_confidence: float = 0.0,
    limit: int = Query(200, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
    polystore: PolystoreEngine = Depends(get_polystore_engine),
    tenant_id: str = Depends(get_tenant_id),
):
    """List skills in the registry with filtering (tenant-scoped).

    The three summary numbers are aggregated in SQL over the WHOLE filtered set,
    while only `limit` rows are returned. That split is the point: computing them
    from the returned rows instead would make `total` mean "page size" and skew
    the execution-weighted success rate toward whatever happened to be on the
    page, which is a silent wrong answer rather than a visible truncation.
    """
    conds = [
        Skill.confidence >= min_confidence,
        Skill.tenant_id == tenant_id,
    ]
    if department:
        conds.append(Skill.department == department)
    if status:
        conds.append(Skill.status == status)

    total, total_exec, weighted = (await db.execute(
        select(
            sqlfunc.count(Skill.id),
            sqlfunc.coalesce(sqlfunc.sum(Skill.execution_count), 0),
            sqlfunc.coalesce(sqlfunc.sum(Skill.success_rate * Skill.execution_count), 0.0),
        ).where(*conds)
    )).one()
    total_exec = int(total_exec or 0)
    avg_sr = (float(weighted) / total_exec) if total_exec > 0 else 0.0

    skills = (await db.execute(
        select(Skill)
        .where(*conds)
        .order_by(Skill.confidence.desc())
        .limit(limit)
    )).scalars().all()

    return SkillRegistryResponse(
        total=int(total or 0),
        total_executions=total_exec,
        avg_success_rate=round(avg_sr, 3),
        skills=[SkillSummary.model_validate(s.__dict__) for s in skills],
    )


@router.get("/{skill_id}", response_model=SkillDetail)
async def get_skill(
    skill_id: str,
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """Get full skill detail — this tenant's only (had no tenant filter, so any
    tenant could read another's full skill definition and reasoning by id)."""
    result = await db.execute(
        select(Skill).where(
            Skill.tenant_id == tenant_id,
            (Skill.skill_id == skill_id) | (Skill.id == skill_id),
        )
    )
    skill = result.scalar_one_or_none()
    if not skill:
        raise HTTPException(404, "Skill not found")
    return SkillDetail.model_validate(skill.__dict__)


@router.post("/{skill_id}/execute", response_model=SkillExecutionResponse)
async def execute_skill(
    skill_id: str,
    body: SkillExecutionRequest,
    background_tasks: BackgroundTasks,
    tenant: dict = Depends(require_role("operator")),
    _allowance: dict = Depends(require_execution_allowance()),
    db: AsyncSession = Depends(get_db),
):
    """Execute a skill — full L9 pipeline: route → execute → report to L10. Requires operator role.

    Managed cloud only: fails closed with 429 past the plan's runaway hard cap
    (overage up to the cap is allowed because it is billed). No-op for self-host.
    """
    tenant_id = tenant["tenant_id"]
    # 1. Find skill — this tenant's. Was found by id alone, so any tenant could
    # RUN another tenant's skill (writing an execution under the victim tenant).
    result = await db.execute(
        select(Skill).where(
            Skill.tenant_id == tenant_id,
            (Skill.skill_id == skill_id) | (Skill.id == skill_id),
        )
    )
    skill = result.scalar_one_or_none()
    if not skill:
        raise HTTPException(404, "Skill not found")

    exec_id = str(uuid.uuid4())
    start = datetime.now(timezone.utc)

    # Trust boundary: these context keys are server-set only. A client planting
    # them in the request body must not be able to claim human approval (SOX
    # gate) or Gate 3 pre-approval, so they are stripped before the context is
    # passed anywhere downstream.
    exec_context = dict(body.context or {})
    for _trusted_key in ("hitl_pre_approved", "has_human_approver"):
        exec_context.pop(_trusted_key, None)

    # 2. Pre-execution guardrails (route-level throttle; runs before the
    # pipeline so a rate-limited caller never burns gate model calls).
    pre_guards = skill.guardrails.get("pre_execution", []) if skill.guardrails else []
    for guard in pre_guards:
        if isinstance(guard, str) and "rate_limit" in guard:
            recent_q = select(sqlfunc.count(SkillExecution.id)).where(
                SkillExecution.skill_db_id == skill.id,
                SkillExecution.started_at >= datetime(
                    start.year, start.month, start.day, start.hour, tzinfo=timezone.utc
                ),
            )
            count_res = await db.execute(recent_q)
            if (count_res.scalar() or 0) >= 50:
                return SkillExecutionResponse(
                    execution_id=exec_id, skill_id=skill.skill_id,
                    status=ExecutionStatus.BLOCKED_RATE_LIMIT, route_type="SKILL_EXEC",
                    duration_ms=0, hitl_required=False,
                )

    # 3. The ONE gate pipeline. This route used to re-implement a partial
    # inline pipeline (compliance + confidence only), silently skipping
    # Gate 2 (Fairness) and Gate 4 (Debate) - and since the MCP execute_skill
    # tool forwards here, agents inherited the same holes. It now runs
    # AgentExecutor.execute_skill, the same path missions use: compliance +
    # fairness concurrently, the autonomy-dial confidence/consequence gate
    # (which pauses to the durable HITL queue), debate, execution, governed
    # actuation, post-audit, and provenance.
    from app.agents.runtime import AgentExecutor
    from app.services.hitl_manager import hitl_manager

    skill_dict = {
        "skill_id": skill.skill_id,
        # Lets a Gate-3 pause resume from the compiled Skill row even after
        # the 24h gate-cache record expires.
        "skill_db_id": skill.id,
        "department": skill.department,
        "domain": skill.domain,
        "steps": skill.steps or [],
        "compliance_tags": skill.compliance_tags or [],
        "confidence": skill.confidence or 0.0,
        "guardrails": skill.guardrails or {},
        "always_hitl": bool(getattr(skill, "always_hitl", False)),
    }
    exec_context.update({
        "intent": body.intent,
        "tenant_id": skill.tenant_id,
        "execution_id": exec_id,
        "_skill_obj": skill,
    })

    executor = AgentExecutor(compliance_engine, hitl_manager)
    result = await executor.execute_skill(skill_dict, exec_context)
    status = result.get("status", ExecutionStatus.FAILED)

    # 4. Feedback loop on terminal outcomes (a pause is not an outcome yet).
    hitl_required = status in PENDING_STATUSES
    if not hitl_required:
        await feedback_engine.process_agent_outcome({
            "status": status, "rule_id": skill.skill_id
        })

    return SkillExecutionResponse(
        execution_id=result.get("execution_id", exec_id),
        skill_id=skill.skill_id,
        status=status,
        route_type="SKILL_EXEC",
        reasoning_chain=result.get("reasoning_chain", []),
        duration_ms=result.get("duration_ms", result.get("pipeline_ms", 0)),
        hitl_required=hitl_required,
    )


@router.get("/{skill_id}/executions")
async def get_executions(
    skill_id: str,
    limit: int = Query(20, le=100),
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """This tenant's execution history for a skill (had no tenant filter, so any
    tenant could read another's executions incl. task_intent and reasoning)."""
    result = await db.execute(
        select(SkillExecution)
        .where(
            SkillExecution.tenant_id == tenant_id,
            SkillExecution.skill_id_name == skill_id,
        )
        .order_by(SkillExecution.started_at.desc())
        .limit(limit)
    )
    execs = result.scalars().all()
    return [
        {
            "id": e.id,
            "status": e.status,
            "route_type": e.route_type,
            "task_intent": e.task_intent,
            "duration_ms": e.duration_ms,
            "hitl_required": e.hitl_required,
            "outcome_type": e.outcome_type,
            "confidence_delta": e.confidence_delta,
            "started_at": e.started_at.isoformat() if e.started_at else None,
            "reasoning_chain": e.reasoning_chain,
        }
        for e in execs
    ]

# Newest-first cap on the approval queue read. Deep history belongs in the
# ledger views, not in a badge poll.
_PENDING_HITL_CAP = 200


@router.get("/hitl/pending")
async def get_pending_hitl(
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """L9 - This tenant's pending HITL executions.

    Had no tenant dependency: it returned every tenant's approval queue,
    including each execution's `context` payload.

    Bounded and slimmed, because this is the hottest read in the product: the
    app shell polls it every 30 seconds for every signed-in user on every page.
    PENDING_HITL is a queue, not a window, so a stalled approver or a weekend
    grows it monotonically. `context` is the full stored request payload and no
    surface renders it (the queue shows `reasoning_chain`), so it is not sent.
    """
    result = await db.execute(
        select(SkillExecution)
        .where(
            SkillExecution.tenant_id == tenant_id,
            SkillExecution.hitl_required == True,
            SkillExecution.status == ExecutionStatus.PENDING_HITL,
        )
        .order_by(SkillExecution.started_at.desc())
        .limit(_PENDING_HITL_CAP)
    )
    execs = result.scalars().all()
    return [
        {
            "id": e.id,
            "skill_id_name": e.skill_id_name,
            "status": e.status,
            "route_type": e.route_type,
            "task_intent": e.task_intent,
            "started_at": e.started_at.isoformat() if e.started_at else None,
            "reasoning_chain": e.reasoning_chain,
        }
        for e in execs
    ]

def _approver_identity(tenant: dict) -> str:
    """Attributable approver from the AUTHENTICATED principal (never client text)."""
    return (
        tenant.get("email")
        or tenant.get("user_id")
        or tenant.get("name")
        or f"{tenant.get('tenant_id', 'unknown')}:{tenant.get('role', 'unknown')}"
    )


class ApproveHitlIn(BaseModel):
    """Optional approval payload. `corrected_answer` turns a plain approval into
    an APPROVE-WITH-EDIT: the human accepted the action but rewrote the answer."""
    corrected_answer: str | None = None


@router.post("/hitl/{exec_id}/approve")
async def approve_hitl(
    exec_id: str,
    body: ApproveHitlIn | None = None,
    tenant: dict = Depends(require_role("operator")),
    db: AsyncSession = Depends(get_db),
):
    """L9 - Approve a pending HITL execution (your own tenant's only).

    Operator+ only: approving RESUMES and runs the paused skill, so a viewer
    must not be able to. Tenant-isolated by the query below; approver recorded
    is the authenticated principal, not free text.

    Every approval goes through hitl_manager.resolve_hitl - the same resolve
    path as the email-link approver - which actually RUNS the paused skill.
    The final status is stamped by the executor when the resumed run
    completes; this route never marks work SUCCESS that has not run. (It used
    to: it stamped SUCCESS_CLEAN unconditionally and only resumed when a
    gate-cache record happened to survive.)

    Supplying `corrected_answer` records an approval WITH AN EDIT: the human's
    rewrite is captured as a Foundry training example (the strongest
    supervised signal the platform can collect) and rides in the execution
    context so the resumed run finalizes as SUCCESS_WITH_EDIT - human-edited
    fallout in the safe-autonomy breakdown, not clean autonomy.
    """
    tenant_id = tenant["tenant_id"]
    approver = _approver_identity(tenant)
    result = await db.execute(
        select(SkillExecution).where(
            SkillExecution.id == exec_id, SkillExecution.tenant_id == tenant_id
        )
    )
    execution = result.scalar_one_or_none()
    if not execution:
        raise HTTPException(404, "Execution not found")
    # A department-scoped operator must not approve another department's paused
    # action. hitl.py enforces this on its own resolve routes; this sibling
    # endpoint resumes the same skill via the same resolve_hitl, so it needs the
    # identical gate or it is a scope bypass.
    from app.services.hitl_manager import hitl_manager
    from app.core.tenant import check_department_scope
    check_department_scope(tenant, await hitl_manager.get_record_department(exec_id))
    if execution.status != ExecutionStatus.PENDING_HITL and execution.agent_state not in (
        AgentState.PAUSED, AgentState.PENDING_HITL
    ):
        raise HTTPException(409, "Execution is not awaiting approval")

    edit = (body.corrected_answer or "").strip() if body else ""
    if edit:
        execution.context = {**(execution.context or {}), "human_corrected_answer": edit}
        await db.commit()
        # An edit is ground truth authored by the enterprise's own expert: capture
        # it as a CORRECTED training example. Never fatal to the approval itself.
        try:
            from app.services.foundry import dataset_builder
            await dataset_builder.record_human_feedback(
                db, tenant_id, execution_id=exec_id, corrected_answer=edit)
        except Exception as e:
            logger.error(f"[HITL] could not record the correction for {exec_id}: {e}")

    resolved = await hitl_manager.resolve_hitl(
        exec_id, approved=True, approver=approver, tenant_id=tenant_id
    )
    if not resolved:
        raise HTTPException(409, "Approval was already resolved")

    await activity_feed.emit(
        event_type=ActivityEventType.HITL_APPROVED,
        title=f"HITL approved: {execution.skill_id_name}",
        description=(
            f"Human approved execution of '{execution.task_intent or 'unknown'}'"
            + (" after editing the answer" if edit else "")
            + "; the skill is resuming."
        ),
        tenant_id=execution.tenant_id,
        severity=ActivitySeverity.INFO,
        source_type="execution", source_id=exec_id,
    )

    await record_security_event(
        tenant_id=tenant_id, event_type="HITL_DECISION", action="APPROVE",
        actor=approver, actor_role=tenant.get("role"),
        resource_type="skill_execution", resource_id=exec_id,
    )
    return {"status": "RESUMING", "execution_id": exec_id}

@router.post("/hitl/{exec_id}/reject")
async def reject_hitl(
    exec_id: str,
    background_tasks: BackgroundTasks,
    tenant: dict = Depends(require_role("operator")),
    db: AsyncSession = Depends(get_db),
):
    """L9 - Reject a pending HITL execution (operator+, your own tenant's only)."""
    tenant_id = tenant["tenant_id"]
    approver = _approver_identity(tenant)
    result = await db.execute(
        select(SkillExecution).where(
            SkillExecution.id == exec_id, SkillExecution.tenant_id == tenant_id
        )
    )
    execution = result.scalar_one_or_none()
    if not execution:
        raise HTTPException(404, "Execution not found")
    # Same department-scope gate as approve: rejecting is a scoped action too.
    from app.services.hitl_manager import hitl_manager
    from app.core.tenant import check_department_scope
    check_department_scope(tenant, await hitl_manager.get_record_department(exec_id))

    execution.status = ExecutionStatus.HUMAN_OVERRIDDEN
    execution.outcome_type = ExecutionStatus.HUMAN_OVERRIDDEN
    execution.hitl_approved = False
    execution.completed_at = datetime.now(timezone.utc)

    # Emit activity event
    await activity_feed.emit(
        event_type=ActivityEventType.HITL_REJECTED,
        title=f"HITL rejected: {execution.skill_id_name}",
        description=f"Human rejected execution of '{execution.task_intent or 'unknown'}'.",
        tenant_id=execution.tenant_id,
        severity=ActivitySeverity.WARNING,
        source_type="execution", source_id=exec_id,
    )

    # L10: Trigger elicitation on human override
    from app.services.evolution import EvolutionEngine
    background_tasks.add_task(
        EvolutionEngine.handle_agent_failure,
        exec_id, execution.task_intent or "",
        execution.context or {}, execution.skill_id_name or "",
        "unknown", execution.tenant_id
    )

    await db.commit()

    # Close the gate-cache record too so both stores agree.
    gate_record = await hitl_manager._get_record(exec_id)
    if gate_record and gate_record.get("status") == "PENDING":
        await hitl_manager.resolve_hitl(
            exec_id, approved=False, approver=approver, tenant_id=tenant_id
        )

    await record_security_event(
        tenant_id=tenant_id, event_type="HITL_DECISION", action="REJECT",
        actor=approver, actor_role=tenant.get("role"),
        resource_type="skill_execution", resource_id=exec_id,
    )
    return {"status": "REJECTED", "execution_id": exec_id}


class CompileRequest(BaseModel):
    workflow_id: str
    domain: str
    workflow_name: str
    required_tools: list[str] = []


@router.post("/compile")
async def compile_skill(body: CompileRequest, tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db)):
    """L8 — Compile rules from a workflow into a SKILL.md agent contract. Requires operator role."""
    tenant_id = tenant["tenant_id"]
    from app.services.compiler import SkillsCompiler
    from app.models.domain import Rule

    # This tenant's rules only: an unfiltered workflow_id match compiled
    # another tenant's rule logic into the returned contract.
    rules_q = await db.execute(
        select(Rule).where(
            Rule.tenant_id == tenant_id,
            Rule.workflow_id == body.workflow_id,
            Rule.is_archived == False,
        )
    )
    rules = rules_q.scalars().all()
    if not rules:
        raise HTTPException(404, "No rules found for this workflow")

    compiler = SkillsCompiler()
    rule_dicts = [
        {"statement": r.statement, "trigger_json": r.trigger_json, "action_json": r.action_json,
         "confidence_scalar": r.confidence_scalar, "compliance_tags": r.compliance_tags or [], "priority": r.version}
        for r in rules
    ]
    contract = compiler.compile_skill(rule_dicts, {
        "workflow_name": body.workflow_name, "domain": body.domain,
        "required_tools": body.required_tools
    })
    # Authoring-time contract check: a step without instruction text would
    # reach the model as ACTION "unknown" and fail silently at run time.
    from app.schemas.skills import validate_steps
    try:
        contract["steps"] = validate_steps(contract["steps"])
    except ValueError as e:
        raise HTTPException(422, detail=f"Compiled skill has invalid steps: {e}")

    # Persist — upsert on skill_id (unique index): recompiling a workflow
    # refreshes the existing skill instead of violating the constraint
    # Upsert within THIS tenant: keyed on skill_id alone, a colliding id
    # overwrote another tenant's skill steps and tool bindings.
    existing_q = await db.execute(
        select(Skill).where(
            Skill.tenant_id == tenant_id, Skill.skill_id == contract["skill_id"]
        )
    )
    existing_skill = existing_q.scalar_one_or_none()
    if existing_skill:
        existing_skill.steps = contract["steps"]
        existing_skill.confidence = contract["confidence"]
        existing_skill.version = contract["version"]
        existing_skill.mcp_tool_bindings = contract["mcp_tool_bindings"]
        existing_skill.compliance_tags = contract["compliance_tags"]
        existing_skill.confidence_tier = existing_skill.confidence_tier or "INFERRED"
        skill_row = existing_skill
    else:
        skill_row = Skill(
            id=str(uuid.uuid4()), skill_id=contract["skill_id"],
            tenant_id=tenant_id, department=body.domain, domain=body.domain,
            version=contract["version"], confidence=contract["confidence"],
            confidence_tier="INFERRED",
            triggers=[], steps=contract["steps"],
            mcp_tool_bindings=contract["mcp_tool_bindings"],
            compliance_tags=contract["compliance_tags"],
        )
        db.add(skill_row)
    await db.commit()

    # Refresh the semantic index (non-blocking: embed_skill never raises, so a
    # failed embed never fails the compile).
    from app.services.knowledge import embed_skill
    await embed_skill(skill_row, tenant_id)

    yaml_output = compiler.export_to_yaml(contract)
    return {"status": "COMPILED", "skill_id": contract["skill_id"], "yaml": yaml_output}


@router.post("/{skill_id}/explain")
async def explain_execution(
    skill_id: str,
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """L15 — Explain THIS tenant's last execution of a skill (was unscoped, so
    any tenant could read another's reasoning chain)."""
    from app.services.platform import ExplainabilityEngine

    exec_q = await db.execute(
        select(SkillExecution)
        .where(
            SkillExecution.tenant_id == tenant_id,
            SkillExecution.skill_id_name == skill_id,
        )
        .order_by(SkillExecution.started_at.desc()).limit(1)
    )
    execution = exec_q.scalar_one_or_none()
    if not execution:
        raise HTTPException(404, "No executions found for this skill")

    engine = ExplainabilityEngine()
    explanation = await engine.explain_action(execution.reasoning_chain or [])
    return explanation
