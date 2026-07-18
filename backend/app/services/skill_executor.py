"""
KAEOS — Gate 5: Skill Execution Engine
Replaces the stub in AgentExecutor.execute_skill() after the Debate gate clears.

Responsibilities:
  - Run each SKILL.md step through the LLM with full context
  - Accumulate a structured reasoning_chain
  - Write a SkillExecution record (timing, status, outcome)
  - Update Skill execution stats + Bayesian confidence
  - Trigger EvolutionEngine on failure so the KB self-heals
  - Append a ProvenanceLedger entry for the execution event
"""
import json
import logging

from app.services.json_utils import compact_context
import time
from datetime import datetime, timezone

from sqlalchemy import select
from app.core.database import AsyncSessionLocal
from app.models.domain import Skill, SkillExecution
from app.services.llm_router import LLMRouter
from app.services.confidence import ConfidenceEngine
from app.services.provenance import ProvenanceEngine
from app.core.context import current_execution_id, current_skill_id, current_tenant_id

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────
_EXEC_SYSTEM_PROMPT = """\
You are the KAEOS AEOS Execution Engine.
You are executing a single step of a verified enterprise skill contract.
Reason carefully. Return ONLY valid JSON matching the schema requested.
Never fabricate tool results. If a tool call would fail, surface the error clearly.
"""

_STEP_PROMPT_TEMPLATE = """\
SKILL: {skill_id}  |  Step {step_num}/{total_steps}  |  Tenant: {tenant_id}
ACTION: {action}
TOOL: {tool}
CONDITION: {condition}
THRESHOLDS: {thresholds}

EXECUTION CONTEXT:
{context}

REASONING CHAIN SO FAR:
{prior_chain}

Execute this step. Return JSON:
{{
  "step_id": "{step_id}",
  "status": "SUCCESS" | "FAILED" | "SKIPPED",
  "tool_called": "<tool name or null>",
  "tool_result": "<result summary or null>",
  "decision": "<what was decided and why>",
  "confidence": 0.0-1.0,
  "side_effects": ["<list of state changes made>"],
  "error": "<error message if FAILED, else null>"
}}

IMPORTANT: "status" describes whether YOU completed this step, not the business
verdict. A negative finding (non-compliant, rejected, high risk) is still
status SUCCESS with the finding in "decision". Use FAILED only if you could
not perform the analysis, and then say why in "error".
"""


class SkillExecutionEngine:
    """
    Gate 5 of the AEOS pipeline — the actual generative execution layer.

    Called by AgentExecutor after Debate/HITL clears. Runs each step in the
    skill's `steps` array sequentially, accumulating a reasoning_chain.
    Persists a SkillExecution record and updates the Skill's live stats.
    """

    def __init__(self):
        self.llm = LLMRouter()
        self.confidence_engine = ConfidenceEngine()
        self.provenance = ProvenanceEngine()
        from app.agents.mcp_tools_dynamic.registry import MCPToolRegistry
        self.tool_registry = MCPToolRegistry()

    async def run(
        self,
        skill: dict,
        context: dict,
        execution_id: str,
        tenant_id: str,
        skill_obj=None,  # ORM Skill object if available
        compliance_warnings: list | None = None,  # non-blocking WARNING violations
    ) -> dict:
        """
        Execute all steps of a skill contract sequentially.

        Returns a result dict with status, reasoning_chain, duration_ms,
        and execution_id — consumed by AgentExecutor to finalize the response.
        """
        start_ts = time.time()
        skill_id = skill.get("skill_id", "unknown")
        steps = skill.get("steps", [])

        # Publish identity for anything downstream (notably the LLM router's
        # cost metering, which otherwise cannot know who to bill).
        # Save previous values so callers' context is not corrupted.
        _prev_tenant = current_tenant_id.get(None)
        _prev_skill = current_skill_id.get(None)
        _prev_exec = current_execution_id.get(None)
        current_tenant_id.set(tenant_id)
        current_skill_id.set(skill_id)
        current_execution_id.set(execution_id)

        compliance_warnings = compliance_warnings or []

        if not steps:
            logger.warning(f"[Exec] Skill {skill_id} has no steps — trivial success.")
            return self._result("SUCCESS_CLEAN", [], execution_id, 0, skill_id)

        reasoning_chain = []
        final_status = "SUCCESS_CLEAN"
        failed_step = None

        logger.info(f"[Exec] Starting {skill_id} ({len(steps)} steps) — exec_id={execution_id}")

        for idx, step in enumerate(steps):
            step_result = await self._execute_step(
                step=step,
                step_num=idx + 1,
                total_steps=len(steps),
                skill_id=skill_id,
                tenant_id=tenant_id,
                context=context,
                prior_chain=reasoning_chain,
            )
            reasoning_chain.append(step_result)

            if step_result.get("status") == "FAILED":
                logger.error(
                    f"[Exec] Step {step.get('id','?')} FAILED: {step_result.get('error')}"
                )
                final_status = "FAILED_RULE_MISMATCH"
                failed_step = step
                break  # Stop on first failure — do not proceed

        duration_ms = int((time.time() - start_ts) * 1000)

        # ── Persist SkillExecution record ──────────────────────────────────
        await self._persist_execution(
            skill=skill,
            skill_obj=skill_obj,
            execution_id=execution_id,
            tenant_id=tenant_id,
            context=context,
            reasoning_chain=reasoning_chain,
            status=final_status,
            duration_ms=duration_ms,
        )

        # ── Update Skill stats + Bayesian confidence ───────────────────────
        if skill_obj is not None:
            await self._update_skill_stats(
                skill_obj=skill_obj,
                succeeded=(final_status == "SUCCESS_CLEAN"),
            )

        # ── Trigger Evolution on failure ───────────────────────────────────
        if final_status != "SUCCESS_CLEAN" and failed_step:
            await self._trigger_evolution(
                execution_id=execution_id,
                task_intent=context.get("intent", skill_id),
                context_data=context,
                skill_id=skill_id,
                department=skill.get("department", "general"),
                tenant_id=tenant_id,
            )

        # ── Provenance ledger entry ────────────────────────────────────────
        if skill_obj is not None:
            await self._write_provenance(
                skill_obj=skill_obj,
                execution_id=execution_id,
                status=final_status,
                confidence=skill.get("confidence", 0.0),
                tenant_id=tenant_id,
                compliance_warnings=compliance_warnings,
            )

        logger.info(
            f"[Exec] {skill_id} → {final_status} in {duration_ms}ms "
            f"({len(reasoning_chain)} steps completed)"
        )

        # Restore caller's context vars.
        current_tenant_id.set(_prev_tenant)
        current_skill_id.set(_prev_skill)
        current_execution_id.set(_prev_exec)

        result = self._result(final_status, reasoning_chain, execution_id, duration_ms, skill_id)
        result["cost"] = await self._decision_cost(execution_id, tenant_id)
        return result

    # ── Private: step execution ───────────────────────────────────────────

    async def _execute_step(
        self,
        step: dict,
        step_num: int,
        total_steps: int,
        skill_id: str,
        tenant_id: str,
        context: dict,
        prior_chain: list,
    ) -> dict:
        """Run one step via LLM and execute tools if requested."""
        action = step.get("action", "")
        # Agents author steps in two shapes: {"action", "tool", ...} and
        # {"step", "name", "prompt"}. The second shape's prompt was silently
        # dropped, leaving the model with ACTION "unknown" (steps then FAILED
        # as "cannot execute"). The instruction text is whichever field holds it.
        action_text = step.get("action") or step.get("prompt") or step.get("name") or "unknown"
        if action == "log":
            return {
                "step_id": step.get("id", f"step_{step_num}"),
                "action": "log",
                "status": "SUCCESS",
                "output": step.get("message", "Step logged."),
                "tool_called": None,
                "tool_result": None,
                "confidence": 1.0,
            }

        target_tool = step.get("tool")
        if target_tool == "none":
            target_tool = None
            
        tool_args_str = ""
        tool_result = None

        if target_tool:
            param_prompt = f"""
We are executing a skill step.
SKILL: {skill_id}
STEP: {step_num}/{total_steps}
ACTION: {action_text}
TOOL: {target_tool}

EXECUTION CONTEXT:
{compact_context(context, max_chars=4000)}

You MUST provide the parameters for the tool '{target_tool}'.
Return ONLY valid JSON representing the parameters. No markdown formatting, just the raw JSON object.
"""
            try:
                raw_params = await self.llm.complete(param_prompt, model_tier="fast", temperature=0.0)
                params_json = _safe_parse_json(raw_params if isinstance(raw_params, str) else raw_params.get("content", "{}"))
                tool_args_str = str(params_json)
                
                logger.info(f"[Exec] Step {step_num} executing tool '{target_tool}' with params {tool_args_str}")
                tool_result = await self.tool_registry.execute_tool(target_tool, params_json)
                logger.info(f"[Exec] Step {step_num} tool result: {tool_result}")
            except Exception as e:
                logger.error(f"[Exec] Tool preparation/execution failed: {e}")
                tool_result = f"Tool execution failed: {e}"

        prompt = _STEP_PROMPT_TEMPLATE.format(
            skill_id=skill_id,
            step_num=step_num,
            total_steps=total_steps,
            tenant_id=tenant_id,
            action=action_text,
            tool=target_tool or "none",
            condition=step.get("condition", "none"),
            thresholds=step.get("thresholds", {}),
            step_id=step.get("id", f"step_{step_num}"),
            context=compact_context(context, max_chars=6000),
            prior_chain=_truncate(_format_chain(prior_chain), 3000),
        )

        if tool_result is not None:
            prompt += f"\n\n--- ACTUAL TOOL OUTPUT ---\n{tool_result}\n\nYou MUST use this actual output. Do NOT hallucinate a different tool result. If the tool output contains an error, record status as FAILED."

        try:
            raw = await self.llm.complete(
                prompt=prompt,
                system_prompt=_EXEC_SYSTEM_PROMPT,
                model_tier="fast",
                temperature=0.0,
                max_tokens=512,
            )
            content = raw if isinstance(raw, str) else raw.get("content", "{}")
            result = _safe_parse_json(content)

            result.setdefault("step_id", step.get("id", f"step_{step_num}"))
            result.setdefault("action", action_text)
            result.setdefault("status", "SUCCESS")
            result.setdefault("tool_called", target_tool)
            result.setdefault("tool_result", tool_result)
            result.setdefault("confidence", 0.8)
            # Verdict-confusion guard: models mark a NEGATIVE FINDING as
            # status FAILED (e.g. "obligation is non-compliant"). A genuine
            # execution failure carries an error and no decision; a completed
            # analysis with a decision and no error is a successful step.
            if (
                result.get("status") == "FAILED"
                and not result.get("error")
                and result.get("decision")
            ):
                result["status"] = "SUCCESS"
                result["verdict_note"] = "reclassified: negative business verdict, step completed"
            return result

        except Exception as exc:
            logger.error(f"[Exec] LLM step execution error on step {step_num}: {exc}")
            return {
                "step_id": step.get("id", f"step_{step_num}"),
                "action": action_text,
                "status": "FAILED",
                "tool_called": target_tool,
                "tool_result": tool_result,
                "decision": "LLM call failed",
                "confidence": 0.0,
                "side_effects": [],
                "error": str(exc),
            }

    # ── Private: persistence ──────────────────────────────────────────────

    async def _persist_execution(
        self,
        skill: dict,
        skill_obj,
        execution_id: str,
        tenant_id: str,
        context: dict,
        reasoning_chain: list,
        status: str,
        duration_ms: int,
    ) -> None:
        # Persist only JSON-safe context. Underscore-prefixed keys (e.g. _skill_obj,
        # _compliance_warnings) are runtime-only objects and are not serialized.
        safe_context = {
            k: v for k, v in context.items()
            if not k.startswith("_") and _is_json_safe(v)
        }
        async with AsyncSessionLocal() as session:
            # Upsert: a HITL-resumed execution already has a PENDING_HITL row
            # under this id - finalize it instead of colliding on insert.
            existing = (await session.execute(
                select(SkillExecution).where(SkillExecution.id == execution_id)
            )).scalar_one_or_none()
            if existing:
                existing.skill_db_id = skill_obj.id if skill_obj else existing.skill_db_id
                existing.skill_id_name = skill.get("skill_id", existing.skill_id_name)
                existing.status = status
                existing.agent_state = "COMPLETED" if status == "SUCCESS_CLEAN" else "FAILED"
                existing.context = safe_context
                existing.reasoning_chain = reasoning_chain
                existing.completed_at = datetime.now(timezone.utc)
                existing.duration_ms = duration_ms
                existing.outcome_type = status
            else:
                session.add(SkillExecution(
                    id=execution_id,
                    skill_db_id=skill_obj.id if skill_obj else None,
                    skill_id_name=skill.get("skill_id", "unknown"),
                    tenant_id=tenant_id,
                    status=status,
                    route_type="SKILL_EXEC",
                    agent_state="COMPLETED" if status == "SUCCESS_CLEAN" else "FAILED",
                    task_intent=context.get("intent", ""),
                    context=safe_context,
                    reasoning_chain=reasoning_chain,
                    completed_at=datetime.now(timezone.utc),
                    duration_ms=duration_ms,
                    outcome_type=status,
                    hitl_required=False,
                ))
            await session.commit()

    async def _update_skill_stats(self, skill_obj, succeeded: bool) -> None:
        """
        Update execution_count, success_rate, and Bayesian confidence on the Skill row.
        Uses the ConfidenceEngine.bayesian_update() already implemented.
        """
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(Skill).where(Skill.id == skill_obj.id)
            )
            skill = result.scalar_one_or_none()
            if not skill:
                return

            skill.execution_count = (skill.execution_count or 0) + 1
            prior_successes = int((skill.success_rate or 0.0) * max(1, skill.execution_count - 1))
            new_successes = prior_successes + (1 if succeeded else 0)
            skill.success_rate = new_successes / skill.execution_count

            # Bayesian confidence update
            evidence = "AGENT_SUCCESS" if succeeded else "AGENT_FAILURE"
            skill.confidence = self.confidence_engine.bayesian_update(
                prior=skill.confidence or 0.5,
                evidence_type=evidence,
            )

            await session.commit()
            logger.info(
                f"[Exec] Skill stats updated: {skill.skill_id} "
                f"count={skill.execution_count} success_rate={skill.success_rate:.3f} "
                f"confidence={skill.confidence:.3f}"
            )

    async def _decision_cost(self, execution_id: str, tenant_id: str) -> dict | None:
        """What THIS decision cost, from its own metered model calls.

        Scoped to the execution, not the skill: "what does one decision cost
        versus a person doing it" is the question, and a skill-wide average
        answers a different one. Local models are genuinely $0 - a measured
        zero, not a missing value.
        """
        try:
            from sqlalchemy import func as sqlfunc

            from app.models.infrastructure import CostEvent
            async with AsyncSessionLocal() as db:
                row = (await db.execute(
                    select(
                        sqlfunc.count(CostEvent.id),
                        sqlfunc.coalesce(sqlfunc.sum(CostEvent.cost_usd), 0.0),
                        sqlfunc.coalesce(sqlfunc.sum(CostEvent.total_tokens), 0),
                        sqlfunc.coalesce(sqlfunc.sum(CostEvent.latency_ms), 0),
                    ).where(
                        CostEvent.tenant_id == tenant_id,
                        CostEvent.execution_id == execution_id,
                    )
                )).one_or_none()
            if not row or not row[0]:
                return None
            calls, total_cost, total_tokens, model_ms = row
            return {
                "model_calls_metered": int(calls),
                "total_cost_usd": round(float(total_cost), 6),
                "total_tokens": int(total_tokens),
                "model_time_ms": int(model_ms),
                "scope": "this decision",
                "note": "local models are $0 - a measured zero, not a missing value",
            }
        except Exception as e:
            logger.debug(f"[Exec] cost summary unavailable: {e}")
            return None

    async def _write_provenance(
        self,
        skill_obj,
        execution_id: str,
        status: str,
        confidence: float,
        tenant_id: str,
        compliance_warnings: list | None = None,
    ) -> None:
        reasoning = f"Gate 5 execution: {status}"
        if compliance_warnings:
            frameworks = ", ".join(
                sorted({w.get("framework", "?") for w in compliance_warnings})
            )
            reasoning += f" | compliance warnings ({frameworks}): {compliance_warnings}"
        async with AsyncSessionLocal() as session:
            await self.provenance.log_event(
                db_session=session,
                rule_id=skill_obj.id,
                event_type="AGENT_EXECUTION",
                actor_hash=_hash_actor(f"aeos_exec_{execution_id}"),
                actor_role="AEOS_RUNTIME",
                evidence_ids=[],
                confidence_at=confidence,
                reasoning=reasoning,
                # MUST pass tenant_id: rule_id here is a SKILL id, so log_event's
                # fallback (backfill from the Rule table) finds nothing and the row
                # would be written with tenant_id=None. On Postgres that violates
                # the provenance_ledger RLS policy and 500s the whole execution;
                # on SQLite (RLS no-op) it silently wrote an unattributed row.
                tenant_id=tenant_id,
            )

    async def _trigger_evolution(
        self,
        execution_id: str,
        task_intent: str,
        context_data: dict,
        skill_id: str,
        department: str,
        tenant_id: str,
    ) -> None:
        """Async fire-and-forget — don't block the execution response."""
        try:
            from app.services.evolution import EvolutionEngine
            await EvolutionEngine.handle_agent_failure(
                execution_id=execution_id,
                task_intent=task_intent,
                context_data=context_data,
                skill_id=skill_id,
                department=department,
                tenant_id=tenant_id,
            )
        except Exception as exc:
            # Evolution failure should never crash the execution response
            logger.error(f"[Exec] EvolutionEngine trigger failed: {exc}")

    # ── Private: helpers ──────────────────────────────────────────────────

    @staticmethod
    def _result(
        status: str,
        reasoning_chain: list,
        execution_id: str,
        duration_ms: int,
        skill_id: str,
    ) -> dict:
        return {
            "status": status,
            "execution_id": execution_id,
            "skill_id": skill_id,
            "steps_completed": len(reasoning_chain),
            "reasoning_chain": reasoning_chain,
            "duration_ms": duration_ms,
        }


def _is_json_safe(value) -> bool:
    """True if a value can be persisted to a JSON column."""
    import json
    try:
        json.dumps(value)
        return True
    except (TypeError, ValueError):
        return False


def _safe_parse_json(raw: str) -> dict:
    import json
    try:
        clean = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        return json.loads(clean)
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"LLM response parse failed: {e}")
        return {"status": "FAILED", "error": f"Could not parse LLM response: {raw[:200]}"}


def _format_chain(chain: list) -> str:
    if not chain:
        return "(none)"
    lines = []
    for s in chain:
        # decision may be a structured object (models following a strict-JSON
        # instruction return dicts) - slicing a dict raises KeyError(slice).
        decision = s.get('decision', '')
        if not isinstance(decision, str):
            decision = json.dumps(decision, default=str)
        lines.append(
            f"  [{s.get('step_id','?')}] {s.get('action','?')} → "
            f"{s.get('status','?')}: {decision[:120]}"
        )
    return "\n".join(lines)


def _truncate(text: str, max_chars: int) -> str:
    return text if len(text) <= max_chars else text[:max_chars] + "…"


def _hash_actor(actor_str: str) -> str:
    import hashlib
    return hashlib.sha256(actor_str.encode()).hexdigest()
