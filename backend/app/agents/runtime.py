"""KAEOS L9 — Agent Runtime (AEOS Enhanced)
SkillRouter + AgentExecutor with Debate Engine and Fairness Engine gates.
"""
from collections import deque
from typing import Dict, Any
import logging
import time

logger = logging.getLogger(__name__)

# Rolling window of recent per-execution gate timings, served by
# GET /metrics/latency. In-process only: it answers "where do the seconds go
# right now", not billing (that is CostEvent's job).
RECENT_STAGE_TIMINGS: deque = deque(maxlen=50)



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
            from app.services.json_utils import extract_json_object
            decision = extract_json_object(content)
            
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

    async def _recall_memory(self, context: dict, skill: Dict[str, Any]) -> None:
        """Inject similar past decisions into the agent's context (pre-deliberation).

        Organizational memory is only worth keeping if it is READ. The recalled
        summaries ride on the context dict, which the executor renders into the
        step prompt (as untrusted content) and persists on the execution row, so
        the reasoning is auditable. Never fatal: a memory miss must not stop a
        governed decision, but it IS logged - silent memory is dead memory.
        """
        try:
            from app.services.memory.enterprise_memory import EnterpriseMemoryService
            recalled = await EnterpriseMemoryService.recall_similar_situations(
                None, context.get("tenant_id", "default"),
                self._memory_key(context, skill), limit=3,
            )
            if recalled:
                context["prior_decisions"] = [
                    {"summary": (r.get("content") or "")[:400],
                     "similarity": round(float(r.get("similarity") or 0.0), 3)}
                    for r in recalled
                ]
        except Exception as e:
            logger.error(f"[Memory] recall failed for {context.get('execution_id')}: {e}")

    async def _store_memory(self, context: dict, skill: Dict[str, Any], result: dict) -> None:
        """Persist this governed decision so future executions can recall it."""
        try:
            from app.services.memory.enterprise_memory import EnterpriseMemoryService
            await EnterpriseMemoryService.store_decision_memory(
                None, context.get("tenant_id", "default"),
                self._memory_key(context, skill),
                {
                    "skill_id": skill.get("skill_id", "unknown"),
                    "execution_id": context.get("execution_id"),
                    "steps_completed": result.get("steps_completed", 0),
                },
                outcome=result.get("status", "SUCCESS_CLEAN"),
            )
        except Exception as e:
            logger.error(f"[Memory] store failed for {context.get('execution_id')}: {e}")

    @staticmethod
    async def _mark_execution_failed(execution_id: str, status: str) -> None:
        """Rewrite the persisted execution row to a failure status.

        The executor already committed SUCCESS_CLEAN before Gate 5b ran, and that
        row is what the safe-autonomy north-star, the Time Machine and the Foundry
        dataset all read. Leaving it green would score a failed governed write as
        safe autonomy.
        """
        try:
            from sqlalchemy import select
            from app.core.database import AsyncSessionLocal
            from app.models.domain import SkillExecution
            async with AsyncSessionLocal() as session:
                row = (await session.execute(
                    select(SkillExecution).where(SkillExecution.id == execution_id)
                )).scalar_one_or_none()
                if row is not None:
                    row.status = status
                    row.outcome_type = status
                    row.agent_state = "FAILED"
                    await session.commit()
        except Exception as e:
            logger.error(f"[Gate 5b] could not mark execution {execution_id} {status}: {e}")

    @staticmethod
    def _memory_key(context: dict, skill: Dict[str, Any]) -> str:
        """The text a decision is remembered and recalled by."""
        intent = context.get("task_intent") or context.get("intent") or ""
        return f"{skill.get('skill_id', 'unknown')}: {intent}".strip()

    async def _emit_gate(self, context: dict, gate: str, state: str, detail: str = "") -> None:
        """Tell the UI a gate just resolved. Transient: WebSocket only.

        The trace used to advance on a timer because nothing reported gate
        transitions - the backend only announced FAILURES. These pings make the
        pipeline the UI draws the pipeline that actually ran.
        """
        # Lap timer: every gate transition already routes through here, so this
        # is the one place that can attribute wall-time to a stage.
        ms = None
        now = time.perf_counter()
        t_prev = context.get("_gate_t_last")
        if t_prev is not None:
            ms = int((now - t_prev) * 1000)
            context.setdefault("_stage_timings", []).append(
                {"gate": gate, "state": state, "ms": ms}
            )
        context["_gate_t_last"] = now
        try:
            from app.api.routes.ws import manager
            from app.core.context import current_actor
            await manager.broadcast_to_tenant(context.get("tenant_id", "default"), {
                "type": "gate_event",
                "execution_id": context.get("execution_id"),
                "skill_id": context.get("_skill_id_name"),
                "gate": gate,
                "state": state,
                "detail": detail,
                "ms": ms,
                # These events are broadcast tenant-wide, so a viewer needs to
                # know whether this run is theirs. None means a background job
                # started it, not a person.
                "actor": current_actor.get(),
            })
        except Exception as e:
            logger.debug(f"[Gate] ws ping skipped: {e}")

    async def execute_skill(
        self, skill: Dict[str, Any], context: Dict[str, Any],
        *, hitl_pre_approved: bool = False,
    ) -> Dict[str, Any]:
        """Executes a skill contract with full AEOS gate pipeline.

        ``hitl_pre_approved`` is trust-bearing: it makes Gate 3 skip the
        confidence/HITL pause. It is a keyword-only argument (never read from
        ``context``) so request-controlled context dicts cannot smuggle it in;
        the only legitimate caller is the mission engine, which derives it from
        a persisted human-approval record.
        """
        t0 = time.perf_counter()
        context["_gate_t_last"] = t0
        context["_stage_timings"] = []
        result = await self._run_gates(skill, context, hitl_pre_approved=hitl_pre_approved)
        total_ms = int((time.perf_counter() - t0) * 1000)
        if isinstance(result, dict):
            stages = context.get("_stage_timings", [])
            result["stage_timings"] = stages
            result["pipeline_ms"] = total_ms
            RECENT_STAGE_TIMINGS.append({
                "execution_id": context.get("execution_id"),
                "tenant_id": context.get("tenant_id", "default"),
                "skill_id": skill.get("skill_id", "unknown"),
                "status": result.get("status"),
                "pipeline_ms": total_ms,
                "stages": stages,
            })
            logger.info(
                "[Latency] %s %s pipeline=%dms %s",
                context.get("execution_id"), result.get("status"), total_ms,
                " ".join(f"{s['gate']}:{s['ms']}ms" for s in stages),
            )
        return result

    async def _run_gates(
        self, skill: Dict[str, Any], context: Dict[str, Any],
        *, hitl_pre_approved: bool = False,
    ) -> Dict[str, Any]:
        # Defense in depth: strip trust-bearing keys a caller (or a request
        # body flowing into context) may have planted. They are server-set only.
        context.pop("hitl_pre_approved", None)

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

        # ── Gates 1+2: Compliance Pre-Check (L13) + Fairness (AEOS P3) ──
        # The two gates are independent (neither reads the other's output), and
        # each can make a real model call - so when both apply they run
        # concurrently. Verdict ordering is preserved: a compliance BLOCKER is
        # checked (and returned) first, exactly as in the sequential pipeline.
        # NOTE: check_before_execution is async — it MUST be awaited. A prior
        # bug called it without await, yielding a truthy coroutine that blocked
        # every execution as BLOCKED_COMPLIANCE.
        import asyncio

        skill_obj = context.get("_skill_obj")
        fairness_result = None
        if skill_obj and self.fairness_engine.requires_fairness_check(skill_obj, context):
            violations, fairness_result = await asyncio.gather(
                self.compliance.check_before_execution(
                    skill.get("compliance_tags", []), context
                ),
                self.fairness_engine.score_fairness(
                    skill_obj, context,
                    tenant_id=context.get("tenant_id", "default"),
                    execution_id=context.get("execution_id"),
                ),
            )
        else:
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

        if fairness_result is not None:
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
        from app.core.config import get_settings
        _settings = get_settings()
        effective_confidence = skill.get("confidence", 0)
        try:
            from app.services.llm_router import LLMRouter
            _router = await LLMRouter.for_tenant(context.get("tenant_id", "default"))
            effective_confidence = min(
                effective_confidence, _router.confidence_ceiling("reasoning")
            )
        except Exception as e:
            # FAIL CLOSED: if the tenant's measured ceiling cannot be read
            # (Redis/DB down, cold cache, provider timeout), the skill's raw
            # declared confidence must NOT stand in for it. Apply the failsafe
            # ceiling, which sits below the autonomous-execution threshold, so
            # the decision routes to a human until the lookup recovers.
            effective_confidence = min(
                effective_confidence, _settings.FAILSAFE_CONFIDENCE_CEILING
            )
            logger.error(
                f"[Gate3] Tenant ceiling lookup failed; failsafe ceiling "
                f"{_settings.FAILSAFE_CONFIDENCE_CEILING} applied (fail-closed): {e}"
            )
            await self._emit_gate(
                context, "confidence", "failsafe",
                f"ceiling lookup failed; failsafe cap {_settings.FAILSAFE_CONFIDENCE_CEILING} applied",
            )
            try:
                from app.models.agent_factory import ActivityEventType, ActivitySeverity
                await self.activity_feed.emit(
                    event_type=ActivityEventType.PROACTIVE_ALERT,
                    title=f"Gate 3 failsafe engaged: {skill.get('skill_id', 'unknown')}",
                    description=(
                        "Tenant confidence-ceiling lookup failed; the failsafe ceiling "
                        f"({_settings.FAILSAFE_CONFIDENCE_CEILING}) was applied and the "
                        "decision routes to a human."
                    ),
                    tenant_id=context.get("tenant_id", "default"),
                    severity=ActivitySeverity.WARNING,
                    source_type="execution",
                    source_id=context.get("execution_id"),
                )
            except Exception as feed_err:
                # Best-effort visibility only; the fail-closed cap above already
                # holds regardless of whether this event lands.
                logger.debug(f"[Gate3] failsafe activity event skipped: {feed_err}")

        # Two independent reasons to route to a human:
        #  (a) confidence below the CONFIGURED autonomous-exec threshold (this
        #      used to be a hardcoded 0.82 literal that ignored the config knob);
        #  (b) HIGH-CONSEQUENCE actions (payments, terminations, contract
        #      execution, external sends, irreversible/data-deletion) ALWAYS go
        #      to a human, regardless of confidence — you don't let a model wire
        #      money on its own no matter how sure it is.
        # The Autonomy Dial: per-domain risk appetite set by an executive overrides
        # the platform default threshold (falls back to it when unset). Gives the
        # dial real teeth at the confidence gate.
        from app.services.autonomy_policy import resolve_min_confidence
        _threshold = await resolve_min_confidence(
            context.get("tenant_id", "default"), skill.get("department"),
        )
        # Shared helper (explicit always_hitl flag first, tag inference as an
        # escalate-only fallback). The persisted Skill row is checked too: the
        # executor's skill dict may not carry the explicit flag.
        from app.services.consequence import is_high_consequence
        _high_consequence = is_high_consequence(skill) or is_high_consequence(skill_obj)

        # A mission step that already cleared its mission-level HITL checkpoint
        # carries an explicit human approval, so Gate 3 must not re-pause it — the
        # human gate has already been satisfied upstream. The flag arrives ONLY
        # via the keyword-only argument (backed by a persisted approval record at
        # the mission engine); context-supplied values are stripped at entry, so
        # request-controlled data can never claim pre-approval.
        _pre_approved = bool(hitl_pre_approved)

        if not _pre_approved and (_high_consequence or effective_confidence < _threshold):
            if _high_consequence:
                logger.info(f"[Gate3] high-consequence action -> forcing HITL: {skill.get('skill_id')}")
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

        # ── Enterprise memory: what happened last time we faced this? ───
        # Recalled BEFORE deliberation so the debate and the execution both
        # reason over the organization's own history, not a blank slate.
        await self._recall_memory(context, skill)

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
                if decision in ("BLOCK", "ESCALATE"):
                    # Record the lap on the stopping path too, or the latency
                    # trace omits the single most expensive gate.
                    await self._emit_gate(context, "debate", decision.lower())

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
        await self._emit_gate(context, "execute", "passed")

        # ── Gate 5b: Governed actuation (autonomy that DOES) ─────────────
        # A skill may declare an `actuation` intent {system, object_type,
        # external_id, operation, payload}. Because we only reach here AFTER the
        # compliance / fairness / confidence-HITL / debate gates have passed, the
        # write-back inherits full governance. Idempotent + reversible.
        #
        # FAILS CLOSED. A human approved an ACTION, not a paragraph: if the write
        # to the system of record does not land, the execution is a FAILURE even
        # though the skill produced output. Swallowing the error here reported
        # SUCCESS_CLEAN and let the mission engine mark the step DONE for a write
        # that never happened - the worst possible lie in a governed-autonomy
        # product. Partial-failure semantics are preserved in the payload:
        # `skill_output_produced` says the reasoning succeeded, the status says
        # the world was not changed.
        _actuation = skill.get("actuation") if isinstance(skill, dict) else None
        if _actuation and isinstance(_actuation, dict):
            try:
                from app.services.actuation import Actuator
                from app.core.database import AsyncSessionLocal
                async with AsyncSessionLocal() as _adb:
                    _rec = await Actuator.apply_action(
                        _adb, tenant_id=context["tenant_id"],
                        system=_actuation.get("system", "sandbox"),
                        object_type=_actuation.get("object_type", "record"),
                        external_id=str(_actuation.get("external_id", exec_id)),
                        operation=_actuation.get("operation", "UPDATE"),
                        payload=_actuation.get("payload", {}),
                        execution_id=exec_id,
                        actor=skill.get("skill_id", "agent"),
                    )
                    logger.info(f"[Gate 5b] actuated {_rec.system}:{_rec.external_id} -> {_rec.status}")
            except Exception as e:
                _target = (f"{_actuation.get('system', 'sandbox')}:"
                           f"{_actuation.get('external_id', exec_id)}")
                logger.error(
                    f"[Gate 5b] actuation FAILED for {exec_id} ({_target}); the "
                    f"execution is reported as FAILED_ACTUATION (fail-closed): {e}"
                )
                await self._mark_execution_failed(exec_id, "FAILED_ACTUATION")
                await self._emit_gate(context, "execute", "failed",
                                      f"governed write to {_target} failed")
                from app.models.agent_factory import ActivityEventType, ActivitySeverity
                await self.activity_feed.emit(
                    event_type=ActivityEventType.AGENT_FAILED,
                    title=f"Governed write failed: {skill.get('skill_id', 'unknown')}",
                    description=(
                        f"The skill produced its output but the approved write to "
                        f"{_target} did not land, so nothing changed in that system: {e}"
                    ),
                    tenant_id=context["tenant_id"],
                    severity=ActivitySeverity.ACTION_REQUIRED,
                    source_type="execution",
                    source_id=exec_id,
                    requires_action=True,
                )
                return {
                    "status": "FAILED_ACTUATION",
                    "execution_id": exec_id,
                    "reason": f"Approved write to {_target} failed: {e}",
                    "skill_output_produced": True,
                    "actuation_target": _target,
                    "reasoning_chain": exec_result.get("reasoning_chain", []),
                    "steps_completed": exec_result.get("steps_completed", 0),
                    "duration_ms": exec_result.get("duration_ms", 0),
                    "cost": exec_result.get("cost"),
                    "warnings": warnings,
                }

        # ── Gate 6: Post-Execution Audit ─────────────────────────────────
        audit_passed = self.compliance.enforce_audit_requirements(
            skill.get("compliance_tags", []), context
        )
        if not audit_passed:
            logger.error("Audit post-execution checks failed.")
            return {"status": "FAILED_AUDIT", "warnings": warnings}
        await self._emit_gate(context, "audit", "passed")

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

        # The decision cleared every gate: remember it, so the next similar
        # situation starts from what this organization already did.
        await self._store_memory(context, skill, result)
        return result
