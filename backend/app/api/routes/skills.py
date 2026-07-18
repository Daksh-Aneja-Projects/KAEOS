"""KAEOS — Skills Registry API (L8 Compiler + L9 Runtime + L10 Feedback)"""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func as sqlfunc
from datetime import datetime, timezone
import uuid

from app.core.database import get_db
from app.core.tenant import get_tenant_id
from app.models.domain import Skill, SkillExecution
from app.services.knowledge import PolystoreEngine
from app.core.dependencies import get_polystore_engine
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

router = APIRouter(prefix="/skills", tags=["Skills — L8 Registry"])
confidence_engine = ConfidenceEngine()
feedback_engine = FeedbackEngine()
activity_feed = ActivityFeedService()
compliance_engine = ComplianceEngine()


@router.get("/", response_model=SkillRegistryResponse)
async def list_skills(
    department: str | None = None,
    status: str | None = None,
    min_confidence: float = 0.0,
    db: AsyncSession = Depends(get_db),
    polystore: PolystoreEngine = Depends(get_polystore_engine),
    tenant_id: str = Depends(get_tenant_id),
):
    """List all skills in the registry with filtering (tenant-scoped)."""
    q = select(Skill).where(
        Skill.confidence >= min_confidence,
        Skill.tenant_id == tenant_id,
    )
    if department:
        q = q.where(Skill.department == department)
    if status:
        q = q.where(Skill.status == status)
    q = q.order_by(Skill.confidence.desc())

    result = await db.execute(q)
    skills = result.scalars().all()

    total_exec = sum(s.execution_count for s in skills)
    avg_sr = (
        sum(s.success_rate * s.execution_count for s in skills) / total_exec
        if total_exec > 0 else 0.0
    )

    return SkillRegistryResponse(
        total=len(skills),
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
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """Execute a skill — full L9 pipeline: route → execute → report to L10."""
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

    # 2. L13 Compliance pre-check
    # check_before_execution is async — an un-awaited coroutine is always truthy
    # and silently blocked every tagged skill (see app/agents/runtime.py:159)
    compliance_violations = await compliance_engine.check_before_execution(
        skill.compliance_tags or [], body.context or {}
    )
    if compliance_violations:
        return SkillExecutionResponse(
            execution_id=exec_id, skill_id=skill.skill_id,
            status="BLOCKED_COMPLIANCE", route_type="SKILL_EXEC",
            duration_ms=0, hitl_required=False,
        )

    # 3. Pre-execution guardrails
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
                    status="BLOCKED_RATE_LIMIT", route_type="SKILL_EXEC",
                    duration_ms=0, hitl_required=False,
                )

    # 3. Confidence gate — HITL check.
    # BYOK adaptation: a tenant's own model can only claim as much confidence as
    # its capability probe earned it. A weaker model lowers effective confidence,
    # so more of its decisions fall below the threshold and route to a human.
    from app.services.llm_router import LLMRouter

    _router = await LLMRouter.for_tenant(skill.tenant_id)
    effective_confidence = min(skill.confidence, _router.confidence_ceiling("reasoning"))
    hitl_required = effective_confidence < 0.82
    if hitl_required:
        execution = SkillExecution(
            id=exec_id,
            skill_db_id=skill.id,
            skill_id_name=skill.skill_id,
            tenant_id=skill.tenant_id,
            status="PENDING_HITL",
            route_type="SKILL_EXEC",
            agent_state="PAUSED",
            task_intent=body.intent,
            context=body.context,
            reasoning_chain=[],
            started_at=start,
            duration_ms=0,
            hitl_required=True,
            outcome_type="PENDING_HITL",
        )
        db.add(execution)
        await db.commit()
        return SkillExecutionResponse(
            execution_id=exec_id, skill_id=skill.skill_id, status="PENDING_HITL",
            route_type="SKILL_EXEC", duration_ms=0, hitl_required=True
        )

    # 4. Actual Generative Skill Execution & Reasoning
    from app.services.skill_executor import SkillExecutionEngine
    exec_engine = SkillExecutionEngine()
    
    # Pass dict representation to run
    skill_dict = skill.__dict__.copy()
    skill_dict["skill_id"] = skill.skill_id
    
    exec_result = await exec_engine.run(
        skill=skill_dict,
        context=body.context or {},
        execution_id=exec_id,
        tenant_id=skill.tenant_id,
        skill_obj=skill
    )

    # 5. Feedback Loop
    await feedback_engine.process_agent_outcome({
        "status": exec_result["status"], "rule_id": skill.skill_id
    })

    return SkillExecutionResponse(
        execution_id=exec_id,
        skill_id=skill.skill_id,
        status=exec_result["status"],
        route_type="SKILL_EXEC",
        reasoning_chain=exec_result["reasoning_chain"],
        duration_ms=exec_result["duration_ms"],
        hitl_required=False,
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

@router.get("/hitl/pending")
async def get_pending_hitl(
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """L9 - This tenant's pending HITL executions.

    Had no tenant dependency: it returned every tenant's approval queue,
    including each execution's `context` payload.
    """
    result = await db.execute(
        select(SkillExecution)
        .where(
            SkillExecution.tenant_id == tenant_id,
            SkillExecution.hitl_required == True,
            SkillExecution.status == "PENDING_HITL",
        )
        .order_by(SkillExecution.started_at.desc())
    )
    execs = result.scalars().all()
    return [
        {
            "id": e.id,
            "skill_id_name": e.skill_id_name,
            "status": e.status,
            "route_type": e.route_type,
            "task_intent": e.task_intent,
            "context": e.context,
            "started_at": e.started_at.isoformat() if e.started_at else None,
            "reasoning_chain": e.reasoning_chain,
        }
        for e in execs
    ]

@router.post("/hitl/{exec_id}/approve")
async def approve_hitl(
    exec_id: str,
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """L9 - Approve a pending HITL execution (your own tenant's only).

    Took no tenant dependency at all and looked the execution up by id, so any
    tenant could approve - and thereby RUN - another tenant's paused skill.
    """
    result = await db.execute(
        select(SkillExecution).where(
            SkillExecution.id == exec_id, SkillExecution.tenant_id == tenant_id
        )
    )
    execution = result.scalar_one_or_none()
    if not execution:
        raise HTTPException(404, "Execution not found")
    
    execution.status = "SUCCESS_CLEAN"
    execution.outcome_type = "SUCCESS_CLEAN"
    execution.hitl_approved = True
    execution.completed_at = datetime.now(timezone.utc)

    # Emit activity event
    await activity_feed.emit(
        event_type=ActivityEventType.HITL_APPROVED,
        title=f"HITL approved: {execution.skill_id_name}",
        description=f"Human approved execution of '{execution.task_intent or 'unknown'}'.",
        tenant_id=execution.tenant_id,
        severity=ActivitySeverity.INFO,
        source_type="execution", source_id=exec_id,
    )

    await db.commit()

    # Gate-3 pipeline pauses carry a resume payload in the hitl_manager cache:
    # approving one actually RUNS the paused skill (not just marks it).
    from app.services.hitl_manager import hitl_manager
    gate_record = await hitl_manager._get_record(exec_id)
    if gate_record and gate_record.get("status") == "PENDING":
        await hitl_manager.resolve_hitl(
            exec_id, approved=True, approver="human", tenant_id=tenant_id
        )

    return {"status": "SUCCESS", "execution_id": exec_id}

@router.post("/hitl/{exec_id}/reject")
async def reject_hitl(
    exec_id: str,
    background_tasks: BackgroundTasks,
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """L9 - Reject a pending HITL execution (your own tenant's only)."""
    result = await db.execute(
        select(SkillExecution).where(
            SkillExecution.id == exec_id, SkillExecution.tenant_id == tenant_id
        )
    )
    execution = result.scalar_one_or_none()
    if not execution:
        raise HTTPException(404, "Execution not found")
    
    execution.status = "HUMAN_OVERRIDDEN"
    execution.outcome_type = "HUMAN_OVERRIDDEN"
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
    from app.services.hitl_manager import hitl_manager
    gate_record = await hitl_manager._get_record(exec_id)
    if gate_record and gate_record.get("status") == "PENDING":
        await hitl_manager.resolve_hitl(
            exec_id, approved=False, approver="human", tenant_id=tenant_id
        )

    return {"status": "REJECTED", "execution_id": exec_id}


class CompileRequest(BaseModel):
    workflow_id: str
    domain: str
    workflow_name: str
    required_tools: list[str] = []


@router.post("/compile")
async def compile_skill(body: CompileRequest, tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    """L8 — Compile rules from a workflow into a SKILL.md agent contract."""
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
    else:
        db.add(Skill(
            id=str(uuid.uuid4()), skill_id=contract["skill_id"],
            tenant_id=tenant_id, department=body.domain, domain=body.domain,
            version=contract["version"], confidence=contract["confidence"],
            confidence_tier="INFERRED",
            triggers=[], steps=contract["steps"],
            mcp_tool_bindings=contract["mcp_tool_bindings"],
            compliance_tags=contract["compliance_tags"],
        ))
    await db.commit()

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
