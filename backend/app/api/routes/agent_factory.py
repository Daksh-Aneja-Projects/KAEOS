"""
KAEOS — Agent Factory API Routes (AEOS Core) — Multi-Tenant Version
Shows the full migration from TENANT = "default" to Depends(get_tenant_id).

This file replaces agent_factory.py.
All other route files (rules.py, skills.py, elicitation.py, etc.) follow
the exact same pattern — swap `TENANT` for `tenant_id: str = Depends(get_tenant_id)`.
"""
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy import select, desc

from app.core.database import AsyncSessionLocal
from app.core.tenant import get_tenant_id, require_role   # ← replaces TENANT = "default"
from app.models.agent_factory import (
    AgentBlueprint, DeployedAgent, DebateTranscript,
)
from app.models.fairness import FairnessAuditLog
from app.schemas.agent_factory import (
    BlueprintCreateRequest, BlueprintRefineRequest, BlueprintApproveRequest,
    DeployRequest, MarkReadRequest, FairnessOverrideRequest, CalendarEventRequest,
)
from app.services.blueprint_generator import BlueprintGenerator
from app.services.compiler import SkillsCompiler
from app.services.activity_feed import ActivityFeedService
from app.services.fairness_engine import FairnessEngine
from app.services.temporal_calendar import TemporalReasoningEngine

router = APIRouter(tags=["Agent Factory"])

blueprint_gen = BlueprintGenerator()
compiler = SkillsCompiler()
activity_svc = ActivityFeedService()
fairness_eng = FairnessEngine()
temporal_eng = TemporalReasoningEngine()

# ─── Blueprint Routes ────────────────────────────────────────────────────────

@router.post("/agents/blueprint")
async def create_blueprint(
    req: BlueprintCreateRequest,
    tenant_id: str = Depends(get_tenant_id),          # ← was: TENANT
):
    """Generate an agent blueprint from a natural language prompt."""
    try:
        result = await blueprint_gen.generate_blueprint(req.prompt, tenant_id, req.created_by)
        return {"status": "blueprint_ready", "blueprint": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/agents/blueprints")
async def list_blueprints(
    tenant_id: str = Depends(get_tenant_id),
):
    """List all agent blueprints for this tenant."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(AgentBlueprint)
            .where(AgentBlueprint.tenant_id == tenant_id)   # ← was: == TENANT
            .order_by(desc(AgentBlueprint.created_at))
            .limit(50)
        )
        blueprints = result.scalars().all()
        return {
            "total": len(blueprints),
            "blueprints": [blueprint_gen._serialize(bp) for bp in blueprints],
        }


@router.get("/agents/blueprint/{blueprint_id}")
async def get_blueprint(
    blueprint_id: str,
    tenant_id: str = Depends(get_tenant_id),
):
    """Get a single blueprint with full graph."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(AgentBlueprint).where(
                AgentBlueprint.id == blueprint_id,
                AgentBlueprint.tenant_id == tenant_id,
            )
        )
        bp = result.scalar_one_or_none()
        if not bp:
            raise HTTPException(status_code=404, detail="Blueprint not found")
        return blueprint_gen._serialize(bp)


@router.put("/agents/blueprint/{blueprint_id}")
async def refine_blueprint(
    blueprint_id: str,
    req: BlueprintRefineRequest,
    tenant_id: str = Depends(get_tenant_id),
):
    """Refine/edit an existing blueprint."""
    try:
        result = await blueprint_gen.refine_blueprint(
            blueprint_id, req.model_dump(exclude_none=True), tenant_id
        )
        return {"status": "updated", "blueprint": result}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/agents/blueprint/{blueprint_id}/approve")
async def approve_blueprint(
    blueprint_id: str,
    req: BlueprintApproveRequest,
    # Approval requires at minimum operator role
    tenant: dict = Depends(require_role("operator")),
):
    """Approve a blueprint for compilation."""
    tenant_id = tenant["tenant_id"]
    try:
        result = await blueprint_gen.approve_blueprint(blueprint_id, tenant_id, req.approved_by)
        return {"status": "approved", "blueprint": result}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/agents/blueprint/{blueprint_id}/compile")
async def compile_blueprint(
    blueprint_id: str,
    tenant: dict = Depends(require_role("operator")),
):
    """Compile an approved blueprint into a SKILL.md agent contract."""
    tenant_id = tenant["tenant_id"]
    try:
        result = await compiler.compile_from_blueprint(blueprint_id, tenant_id)
        return {"status": "compiled", **result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/agents/blueprint/{blueprint_id}/deploy")
async def deploy_agent(
    blueprint_id: str,
    req: DeployRequest,
    # Deployment is admin-only — highest privilege gate
    tenant: dict = Depends(require_role("admin")),
):
    """Deploy an agent from a compiled blueprint."""
    tenant_id = tenant["tenant_id"]
    try:
        result = await compiler.deploy_agent(blueprint_id, tenant_id, req.trigger_config)
        return {"status": "deployed", **result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ─── Deployed Agent Routes ────────────────────────────────────────────────────

@router.get("/agents/deployed")
async def list_deployed_agents(
    tenant_id: str = Depends(get_tenant_id),
):
    """List all deployed agents with status and health."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(DeployedAgent)
            .where(DeployedAgent.tenant_id == tenant_id)
            .order_by(desc(DeployedAgent.created_at))
        )
        agents = result.scalars().all()
        return {
            "total": len(agents),
            "agents": [
                {
                    "id": a.id,
                    "agent_name": a.agent_name,
                    "agent_type": a.agent_type.value if a.agent_type else None,
                    "status": a.status.value if a.status else None,
                    "blueprint_id": a.blueprint_id,
                    "compiled_skill_id": a.compiled_skill_id,
                    "execution_count": a.execution_count,
                    "success_count": a.success_count,
                    "health_status": a.health_status,
                    "last_executed_at": a.last_executed_at.isoformat() if a.last_executed_at else None,
                    "created_at": a.created_at.isoformat() if a.created_at else None,
                }
                for a in agents
            ],
        }


@router.get("/agents/deployed/{agent_id}")
async def get_deployed_agent(
    agent_id: str,
    tenant_id: str = Depends(get_tenant_id),
):
    """Get detailed agent info including health and blueprint."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(DeployedAgent).where(
                DeployedAgent.id == agent_id,
                DeployedAgent.tenant_id == tenant_id,
            )
        )
        agent = result.scalar_one_or_none()
        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")

        bp_result = await session.execute(
            select(AgentBlueprint).where(AgentBlueprint.id == agent.blueprint_id)
        )
        bp = bp_result.scalar_one_or_none()

        return {
            "id": agent.id,
            "agent_name": agent.agent_name,
            "status": agent.status.value if agent.status else None,
            "health_status": agent.health_status,
            "execution_count": agent.execution_count,
            "success_count": agent.success_count,
            "trigger_config": agent.trigger_config,
            "blueprint": blueprint_gen._serialize(bp) if bp else None,
            "created_at": agent.created_at.isoformat() if agent.created_at else None,
        }


@router.post("/agents/deployed/{agent_id}/stop")
async def stop_agent(
    agent_id: str,
    tenant: dict = Depends(require_role("operator")),
):
    tenant_id = tenant["tenant_id"]
    try:
        return await compiler.stop_agent(agent_id, tenant_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/agents/deployed/{agent_id}/pause")
async def pause_agent(
    agent_id: str,
    tenant: dict = Depends(require_role("operator")),
):
    tenant_id = tenant["tenant_id"]
    try:
        return await compiler.pause_agent(agent_id, tenant_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ─── Activity Feed Routes ─────────────────────────────────────────────────────

@router.get("/agents/activity-feed")
async def get_activity_feed(
    limit: int = 50,
    unread_only: bool = False,
    tenant_id: str = Depends(get_tenant_id),
):
    events = await activity_svc.get_feed(tenant_id, limit=limit, unread_only=unread_only)
    counts = await activity_svc.get_unread_count(tenant_id)
    return {"events": events, **counts}


@router.post("/agents/activity-feed/mark-read")
async def mark_feed_read(
    req: MarkReadRequest,
    tenant_id: str = Depends(get_tenant_id),
):
    count = await activity_svc.mark_read(req.event_ids, tenant_id)
    return {"marked": count}


@router.get("/agents/activity-feed/action-required")
async def get_action_required(
    tenant_id: str = Depends(get_tenant_id),
):
    return {"events": await activity_svc.get_action_required(tenant_id)}


# ─── Debate Routes ────────────────────────────────────────────────────────────

@router.get("/agents/debates/recent")
async def get_recent_debates(
    tenant_id: str = Depends(get_tenant_id),
):
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(DebateTranscript)
            .where(DebateTranscript.tenant_id == tenant_id)
            .order_by(desc(DebateTranscript.created_at))
            .limit(20)
        )
        transcripts = result.scalars().all()
        return {
            "transcripts": [
                {
                    "id": t.id,
                    "execution_id": t.execution_id,
                    "skill_id": t.skill_id,
                    "decision": (t.arbitrator_decision or {}).get("decision"),
                    "confidence": (t.arbitrator_decision or {}).get("final_confidence"),
                    "arbitrator_decision": t.arbitrator_decision,
                    "escalated": t.escalated_to_hitl,
                    "duration_ms": t.debate_duration_ms,
                    "created_at": t.created_at.isoformat() if t.created_at else None,
                }
                for t in transcripts
            ]
        }


@router.get("/agents/debates/{execution_id}")
async def get_debate_transcript(
    execution_id: str,
    tenant_id: str = Depends(get_tenant_id),
):
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(DebateTranscript).where(
                DebateTranscript.execution_id == execution_id,
                DebateTranscript.tenant_id == tenant_id,
            )
        )
        transcript = result.scalar_one_or_none()
        if not transcript:
            raise HTTPException(status_code=404, detail="Debate transcript not found")
        return {
            "id": transcript.id,
            "skill_id": transcript.skill_id,
            "tier_level": transcript.tier_level,
            "trigger_reason": transcript.trigger_reason,
            "proposer": transcript.proposer_argument,
            "advocate": transcript.advocate_argument,
            "arbitrator": transcript.arbitrator_decision,
            "duration_ms": transcript.debate_duration_ms,
            "escalated": transcript.escalated_to_hitl,
            "created_at": transcript.created_at.isoformat() if transcript.created_at else None,
        }


# ─── Fairness Routes ──────────────────────────────────────────────────────────

@router.get("/fairness/audit-log")
async def get_fairness_log(
    limit: int = 50,
    tenant_id: str = Depends(get_tenant_id),
):
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(FairnessAuditLog)
            .where(FairnessAuditLog.tenant_id == tenant_id)
            .order_by(desc(FairnessAuditLog.created_at))
            .limit(limit)
        )
        logs = result.scalars().all()
        return {
            "logs": [
                {
                    "id": l.id,
                    "fairness_score": l.fairness_score,
                    "passed": l.passed,
                    "threshold": l.threshold_used,
                    "flagged_attributes": l.flagged_attributes,
                    "rationale": l.rationale,
                    "action_description": l.action_description,
                    "entity_type": l.affected_entity_type,
                    "was_overridden": l.was_overridden,
                    "override_by": l.override_by,
                    "created_at": l.created_at.isoformat() if l.created_at else None,
                }
                for l in logs
            ]
        }


@router.post("/fairness/override/{log_id}")
async def override_fairness(
    log_id: str,
    req: FairnessOverrideRequest,
    # Fairness overrides are admin-only — highest scrutiny
    tenant: dict = Depends(require_role("admin")),
):
    tenant_id = tenant["tenant_id"]
    try:
        return await fairness_eng.override_block(
            log_id, tenant_id, req.override_by, req.justification
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ─── Calendar / Temporal Routes ───────────────────────────────────────────────

@router.get("/calendar/events")
async def list_calendar_events(
    tenant_id: str = Depends(get_tenant_id),
):
    return {"events": await temporal_eng.list_events(tenant_id)}


@router.post("/calendar/events")
async def create_calendar_event(
    req: CalendarEventRequest,
    tenant_id: str = Depends(get_tenant_id),
):
    from datetime import datetime
    data = req.model_dump()
    data["start_date"] = datetime.fromisoformat(data["start_date"])
    data["end_date"] = datetime.fromisoformat(data["end_date"])
    return await temporal_eng.create_event(tenant_id, data)


@router.delete("/calendar/events/{event_id}")
async def delete_calendar_event(
    event_id: str,
    tenant: dict = Depends(require_role("operator")),
):
    tenant_id = tenant["tenant_id"]
    deleted = await temporal_eng.delete_event(event_id, tenant_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Calendar event not found")
    return {"status": "deleted"}


@router.get("/calendar/context")
async def get_temporal_context(
    department: str = "general",
    tenant_id: str = Depends(get_tenant_id),
):
    context = await temporal_eng.get_seasonality_context(department, tenant_id)
    proximity = await temporal_eng.get_deadline_proximity_score("general", tenant_id, department)
    return {"seasonality": context, "deadline_proximity": proximity}
