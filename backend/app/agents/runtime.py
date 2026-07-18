"""KAEOS L9 — Agent Runtime (AEOS Enhanced)
SkillRouter + AgentExecutor with Debate Engine and Fairness Engine gates.
"""
from typing import Dict, Any
import logging

logger = logging.getLogger(__name__)


import json

class SkillRouter:
    """L9 - Multi-Agent Skill Router"""
    
    def __init__(self, registry_client, vector_store):
        self.registry = registry_client
        self.vector = vector_store
        from app.services.llm_router import LLMRouter
        self.llm = LLMRouter()

    async def route_task(self, task_intent: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """Routes a natural language task to the best matching skill."""
        
        # 1. Broad Vector Search to narrow down candidates
        tenant_id = context.get("tenant_id", "default")
        candidates = await self.vector.search_skills(task_intent, tenant_id=tenant_id, top_k=5)
        
        if not candidates:
            logger.warning(f"No skill match for intent: {task_intent}. Falling back to RAG.")
            return {"route_type": "RAG_EXEC", "skill": None}

        # 2. LLM Intent Classification over candidates
        prompt = f"""
Given the following user task intent, choose the best matching skill from the candidates.
If none are a strong match, return "NONE".
Task Intent: {task_intent}

Candidates:
"""
        for i, c in enumerate(candidates):
            prompt += f"{i+1}. {c['skill_id']} (Domain: {c['domain']})\n"
        
        prompt += "\nReturn ONLY valid JSON like: {\"selected_skill_id\": \"skill_name\", \"confidence\": 0.95}"
        
        try:
            raw = await self.llm.complete(
                prompt=prompt,
                model_tier="classification",
                temperature=0.0
            )
            content = raw if isinstance(raw, str) else raw.get("content", "{}")
            clean = content.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            decision = json.loads(clean)
            
            selected = decision.get("selected_skill_id")
            conf = decision.get("confidence", 0.0)
            
            if selected and selected != "NONE" and conf >= 0.8:
                from sqlalchemy import select
                from app.core.database import AsyncSessionLocal
                from app.models.domain import Skill
                async with AsyncSessionLocal() as session:
                    res = await session.execute(select(Skill).where(Skill.skill_id == selected, Skill.tenant_id == tenant_id))
                    skill_obj = res.scalar_one_or_none()
                    if skill_obj:
                        skill_dict = {
                            "id": skill_obj.id,
                            "skill_id": skill_obj.skill_id,
                            "department": skill_obj.department,
                            "steps": skill_obj.steps,
                            "confidence": conf,
                            "compliance_tags": skill_obj.compliance_tags
                        }
                        logger.info(f"LLM routed to skill: {selected} (conf={conf})")
                        return {"route_type": "SKILL_EXEC", "skill": skill_dict}
        except Exception as e:
            logger.error(f"Intent classification failed: {e}")
            
        # 3. Fallback to vector search match
        if candidates[0]['similarity'] > 0.85:
            from sqlalchemy import select
            from app.core.database import AsyncSessionLocal
            from app.models.domain import Skill
            async with AsyncSessionLocal() as session:
                res = await session.execute(select(Skill).where(Skill.id == candidates[0]["skill_db_id"]))
                skill_obj = res.scalar_one_or_none()
                if skill_obj:
                    skill_dict = {
                        "id": skill_obj.id,
                        "skill_id": skill_obj.skill_id,
                        "department": skill_obj.department,
                        "steps": skill_obj.steps,
                        "confidence": candidates[0]['similarity'],
                        "compliance_tags": skill_obj.compliance_tags
                    }
                    logger.info(f"Fuzzy skill match found: {candidates[0]['skill_id']}")
                    return {"route_type": "SKILL_EXEC", "skill": skill_dict}
            
        # 4. RAG Fallback
        logger.warning(f"No strong skill match for intent: {task_intent}. Falling back to RAG.")
        return {"route_type": "RAG_EXEC", "skill": None}


class AgentExecutor:
    """L9 - Execution Engine with AEOS Debate + Fairness gates.
    
    Execution pipeline:
    1. Compliance pre-check (L13)
    2. Fairness gate — if HCM data touched (AEOS P3)
    3. Confidence gate → HITL check
    4. Debate Engine — if Tier-1 action (AEOS P6)
    5. Generative execution
    6. Post-execution audit
    """
    
    def __init__(self, compliance_engine, hitl_manager):
        self.compliance = compliance_engine
        self.hitl = hitl_manager
        # Lazy-load AEOS engines to avoid circular imports
        self._debate_engine = None
        self._fairness_engine = None
        self._activity_feed = None
        self._exec_engine = None

    @property
    def debate_engine(self):
        if self._debate_engine is None:
            from app.services.debate_engine import DebateEngine
            self._debate_engine = DebateEngine()
        return self._debate_engine

    @property
    def fairness_engine(self):
        if self._fairness_engine is None:
            from app.services.fairness_engine import FairnessEngine
            self._fairness_engine = FairnessEngine()
        return self._fairness_engine

    @property
    def activity_feed(self):
        if self._activity_feed is None:
            from app.services.activity_feed import ActivityFeedService
            self._activity_feed = ActivityFeedService()
        return self._activity_feed

    @property
    def exec_engine(self):
        if self._exec_engine is None:
            from app.services.skill_executor import SkillExecutionEngine
            self._exec_engine = SkillExecutionEngine()
        return self._exec_engine



    async def _gate_cost(self, context: dict) -> dict | None:
        """Cost burned before a gate stopped the pipeline.

        A blocked or escalated decision is NOT free: the compliance, fairness
        and debate gates make real model calls. Reporting cost only on the
        success path would understate what governance costs - which is exactly
        the number an evaluator wants to see.
        """
        try:
            from sqlalchemy import func as sqlfunc, select
            from app.core.database import AsyncSessionLocal
            from app.models.infrastructure import CostEvent
            exec_id = context.get("execution_id")
            tenant_id = context.get("tenant_id")
            if not exec_id or not tenant_id:
                return None
            async with AsyncSessionLocal() as db:
                row = (await db.execute(
                    select(
                        sqlfunc.count(CostEvent.id),
                        sqlfunc.coalesce(sqlfunc.sum(CostEvent.cost_usd), 0.0),
                        sqlfunc.coalesce(sqlfunc.sum(CostEvent.total_tokens), 0),
                        sqlfunc.coalesce(sqlfunc.sum(CostEvent.latency_ms), 0),
                    ).where(
                        CostEvent.tenant_id == tenant_id,
                        CostEvent.execution_id == exec_id,
                    )
                )).one_or_none()
            if not row or not row[0]:
                return None
            return {
                "model_calls_metered": int(row[0]),
                "total_cost_usd": round(float(row[1]), 6),
                "total_tokens": int(row[2]),
                "model_time_ms": int(row[3]),
                "scope": "this decision (stopped at a gate)",
            }
        except Exception as e:
            logger.debug(f"[Gate] cost summary unavailable: {e}")
            return None

    async def _emit_gate(self, context: dict, gate: str, state: str, detail: str = "") -> None:
        """Tell the UI a gate just resolved. Transient: WebSocket only.

        The trace used to advance on a timer because nothing reported gate
        transitions - the backend only announced FAILURES. These pings make the
        pipeline the UI draws the pipeline that actually ran.
        """
        try:
            from app.api.routes.ws import manager
            await manager.broadcast_to_tenant(context.get("tenant_id", "default"), {
                "type": "gate_event",
                "execution_id": context.get("execution_id"),
                "skill_id": context.get("_skill_id_name"),
                "gate": gate,
                "state": state,
                "detail": detail,
            })
        except Exception as e:
            logger.debug(f"[Gate] ws ping skipped: {e}")

    async def execute_skill(
        self, skill: Dict[str, Any], context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Executes a skill contract with full AEOS gate pipeline."""
        # Publish identity BEFORE gate 1. The gates themselves make model calls
        # (fairness scoring, debate), so setting this only in the executor
        # (gate 5) left every pre-execution call unattributed - and a decision
        # stopped at a gate looked free when it was not.
        import uuid as _uuid

        from app.core.context import current_execution_id, current_skill_id, current_tenant_id
        context.setdefault("execution_id", f"exec-{_uuid.uuid4().hex[:8]}")
        current_tenant_id.set(context.get("tenant_id", "default"))
        current_skill_id.set(skill.get("skill_id", "unknown"))
        current_execution_id.set(context["execution_id"])
        context["_skill_id_name"] = skill.get("skill_id", "unknown")

        # ── Gate 1: Compliance Pre-Check (L13) ──────────────────────────
        # NOTE: check_before_execution is async — it MUST be awaited. A prior
        # bug called it without await, yielding a truthy coroutine that blocked
        # every execution as BLOCKED_COMPLIANCE.
        violations = await self.compliance.check_before_execution(
            skill.get("compliance_tags", []), context
        )
        blockers = [v for v in violations if v.get("severity") == "BLOCKER"]
        warnings = [v for v in violations if v.get("severity") != "BLOCKER"]
        if blockers:
            await self._emit_gate(context, "compliance", "blocked",
                                  "; ".join(v.get("reason", "") for v in blockers))
            return {
                "status": "BLOCKED_COMPLIANCE",
                "violations": blockers,
                "warnings": warnings,
                "cost": await self._gate_cost(context),
            }
        await self._emit_gate(context, "compliance", "passed")
        # Non-blocking WARNINGs are surfaced downstream (result + provenance).
        context["_compliance_warnings"] = warnings

        # ── Gate 2: Fairness Check (AEOS P3) ────────────────────────────
        skill_obj = context.get("_skill_obj")
        if skill_obj and self.fairness_engine.requires_fairness_check(skill_obj, context):
            fairness_result = await self.fairness_engine.score_fairness(
                skill_obj, context,
                tenant_id=context.get("tenant_id", "default"),
                execution_id=context.get("execution_id"),
            )
            if not fairness_result["passed"]:
                logger.warning(f"Fairness gate BLOCKED: {fairness_result['flagged_attributes']}")
                from app.models.agent_factory import ActivityEventType, ActivitySeverity
                await self.activity_feed.emit(
                    event_type=ActivityEventType.FAIRNESS_BLOCKED,
                    title=f"Fairness gate blocked: {skill.get('skill_id', 'unknown')}",
                    description=fairness_result["rationale"],
                    tenant_id=context.get("tenant_id", "default"),
                    severity=ActivitySeverity.ACTION_REQUIRED,
                    source_type="execution",
                    source_id=context.get("execution_id"),
                    requires_action=True,
                )
                return {
                    "status": "BLOCKED_FAIRNESS",
                    "fairness_score": fairness_result["score"],
                    "flagged_attributes": fairness_result["flagged_attributes"],
                    "rationale": fairness_result["rationale"],
                    "audit_log_id": fairness_result["audit_log_id"],
                }

        await self._emit_gate(context, "fairness", "passed")

        # ── Gate 3: Confidence → HITL Check ─────────────────────────────
        # BYOK: the tenant's probed model ceiling caps every skill's
        # confidence. A weak model mechanically routes more decisions to
        # humans - in the domain-agent path too, not just /skills routes.
        effective_confidence = skill.get("confidence", 0)
        try:
            from app.services.llm_router import LLMRouter
            _router = await LLMRouter.for_tenant(context.get("tenant_id", "default"))
            effective_confidence = min(
                effective_confidence, _router.confidence_ceiling("reasoning")
            )
        except Exception as e:
            logger.warning(f"[Gate3] Tenant ceiling lookup failed (no cap applied): {e}")
        if effective_confidence < 0.82:
            gate_decision = await self.hitl.request_human_confirmation(skill, context)
            # Non-blocking HITL returns immediately with pending=True
            if gate_decision.get("pending"):
                await self._emit_gate(context, "hitl", "paused")
                return {
                    "status": "PENDING_HITL",
                    "execution_id": gate_decision.get("execution_id"),
                    "reason": gate_decision.get("reason", "Awaiting human approval"),
                    "cost": await self._gate_cost(context),
                }
            # If somehow approved/rejected (shouldn't happen with non-blocking), handle it
            if gate_decision.get("approved") is False:
                return {"status": "HUMAN_OVERRIDDEN", "reason": gate_decision.get("reason", "Rejected by human")}

        await self._emit_gate(context, "confidence", "passed")
        await self._emit_gate(context, "hitl", "passed")

        # ── Gate 4: Debate Engine (AEOS P6) ─────────────────────────────
        if skill_obj:
            should_debate, debate_reason = self.debate_engine.should_debate(skill_obj, context)
            if should_debate:
                logger.info(f"Debate Engine triggered for {skill.get('skill_id')}: {debate_reason}")
                transcript = await self.debate_engine.run_debate(
                    skill_obj, context,
                    execution_id=context.get("execution_id", "unknown"),
                    tenant_id=context.get("tenant_id", "default"),
                )
                decision = (transcript.arbitrator_decision or {}).get("decision", "ESCALATE")

                if decision == "BLOCK":
                    from app.models.agent_factory import ActivityEventType, ActivitySeverity
                    await self.activity_feed.emit(
                        event_type=ActivityEventType.DEBATE_BLOCKED,
                        title=f"Debate Engine BLOCKED: {skill.get('skill_id', 'unknown')}",
                        description=(transcript.arbitrator_decision or {}).get("rationale", ""),
                        tenant_id=context.get("tenant_id", "default"),
                        severity=ActivitySeverity.CRITICAL,
                        source_type="execution",
                        source_id=context.get("execution_id"),
                        requires_action=True,
                    )
                    return {
                        "status": "BLOCKED_DEBATE",
                        "debate_decision": decision,
                        "rationale": (transcript.arbitrator_decision or {}).get("rationale"),
                        "transcript_id": transcript.id,
                    }
                elif decision == "ESCALATE":
                    from app.models.agent_factory import ActivityEventType, ActivitySeverity
                    await self.activity_feed.emit(
                        event_type=ActivityEventType.DEBATE_ESCALATED,
                        title=f"Debate escalated to HITL: {skill.get('skill_id', 'unknown')}",
                        tenant_id=context.get("tenant_id", "default"),
                        severity=ActivitySeverity.ACTION_REQUIRED,
                        source_type="execution",
                        source_id=context.get("execution_id"),
                        requires_action=True,
                    )
                    return {
                        "status": "ESCALATED_DEBATE",
                        "debate_decision": decision,
                        "transcript_id": transcript.id,
                        "cost": await self._gate_cost(context),
                    }
                # PROCEED — fall through to Gate 5

        await self._emit_gate(context, "debate", "passed")
        await self._emit_gate(context, "execute", "running")

        # ── Gate 5: Generative Skill Execution ──────────────────────────
        import uuid

        exec_id = context.get("execution_id", f"exec-{uuid.uuid4().hex[:8]}")
        context["execution_id"] = exec_id
        context["tenant_id"] = context.get("tenant_id", "default")

        exec_result = await self.exec_engine.run(
            skill=skill,
            context=context,
            execution_id=exec_id,
            tenant_id=context["tenant_id"],
            skill_obj=skill_obj,
            compliance_warnings=warnings,
        )

        if exec_result["status"] != "SUCCESS_CLEAN":
            from app.models.agent_factory import ActivityEventType, ActivitySeverity
            await self.activity_feed.emit(
                event_type=ActivityEventType.AGENT_FAILED,
                title=f"Execution failed: {skill.get('skill_id', 'unknown')}",
                description=(
                    f"Status: {exec_result['status']} after "
                    f"{exec_result['steps_completed']} steps ({exec_result['duration_ms']}ms)"
                ),
                tenant_id=context["tenant_id"],
                severity=ActivitySeverity.ACTION_REQUIRED,
                source_type="execution",
                source_id=exec_id,
                requires_action=True,
            )
            return exec_result

        logger.info(
            f"[Gate 5] SUCCESS: {skill.get('skill_id', 'unknown')} — "
            f"{exec_result['steps_completed']} steps in {exec_result['duration_ms']}ms"
        )

        # ── Gate 6: Post-Execution Audit ─────────────────────────────────
        audit_passed = self.compliance.enforce_audit_requirements(
            skill.get("compliance_tags", []), context
        )
        if not audit_passed:
            logger.error("Audit post-execution checks failed.")
            return {"status": "FAILED_AUDIT", "warnings": warnings}

        result = {
            "status": "SUCCESS_CLEAN",
            "execution_id": exec_id,
            "reasoning_chain": exec_result.get("reasoning_chain", []),
            "steps_completed": exec_result.get("steps_completed", 0),
            # Carry the measured facts through: this reshaping dropped them,
            # so callers (and the UI) could not show what a decision took.
            "duration_ms": exec_result.get("duration_ms", 0),
            "cost": exec_result.get("cost"),
        }
        if warnings:
            result["warnings"] = warnings
        return result
