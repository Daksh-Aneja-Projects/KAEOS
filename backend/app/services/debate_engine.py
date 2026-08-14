"""KAEOS — Agent Debate Engine (AEOS P6)
Proposer / Devil's Advocate / Arbitrator adversarial reasoning.
"""
import logging
import time
import json

from app.core.database import AsyncSessionLocal
from app.models.agent_factory import DebateTranscript
from app.models.domain import Skill
from app.services.llm_router import LLMRouter, get_tenant_router
from app.services import prompt_guard

logger = logging.getLogger(__name__)

TIER_1_TAGS = {"SOX", "GDPR", "HIPAA", "PCI_DSS", "EEOC", "SOC2"}
DEBATE_CONFIDENCE_THRESHOLD = 0.85
ARBITRATOR_ESCALATION_THRESHOLD = 0.7


class DebateEngine:
    """Adversarial Proposer/Advocate/Arbitrator debate for Tier-1 actions."""

    def __init__(self):
        self.llm = LLMRouter()

    def should_debate(self, skill: Skill, context: dict) -> tuple:
        tags = set(skill.compliance_tags or [])
        overlap = tags & TIER_1_TAGS
        if overlap:
            return True, f"compliance_tag:{','.join(overlap)}"
        if skill.confidence < DEBATE_CONFIDENCE_THRESHOLD:
            return True, "low_confidence"
        if skill.execution_count == 0:
            return True, "first_execution"
        if context.get("force_debate"):
            return True, "explicitly_requested"
        return False, ""

    async def run_debate(self, skill: Skill, context: dict, execution_id: str, tenant_id: str) -> DebateTranscript:
        start = time.time()
        should, reason = self.should_debate(skill, context)

        if not should:
            t = DebateTranscript(
                tenant_id=tenant_id, execution_id=execution_id, skill_id=skill.skill_id,
                tier_level=0, trigger_reason="not_required",
                arbitrator_decision={"final_confidence": skill.confidence, "rationale": "Debate not triggered.", "decision": "PROCEED", "weight_proposer": 0, "weight_advocate": 0},
                debate_duration_ms=0,
            )
            async with AsyncSessionLocal() as session:
                session.add(t)
                await session.commit()
                await session.refresh(t)
            return t

        logger.info(f"[Debate] Starting for {skill.skill_id} — {reason}")
        ctx = self._build_context(skill, context)

        # Bind to THIS tenant's fine-tuned reasoning model (BYOK). Resolved as a
        # local, not stored on self, because a DebateEngine instance is shared
        # across tenants/requests — mutating self.llm would race.
        llm = await get_tenant_router(tenant_id)

        # Turn 1
        proposer = await self._proposer(llm, ctx)
        advocate = await self._advocate(llm, ctx, proposer)
        arbitrator = await self._arbitrator(llm, ctx, proposer, advocate)

        # Turn 2 runs ONLY when turn 1 is contested (latency: a decisive
        # verdict resolves in 3 model calls instead of 5). Contested means the
        # arbitrator landed in or near the ESCALATE band - exactly the cases
        # where a second exchange can genuinely change the outcome. A clear
        # PROCEED (>= 0.8) or clear BLOCK (< 0.5) stands: the advocate has
        # already had its full shot at the proposal, so this skips no scrutiny,
        # only a repeat of it.
        conf_1 = arbitrator.get("final_confidence", 0.5)
        if 0.5 <= conf_1 < 0.8:
            ctx_turn2 = ctx + f"\n\n[PREVIOUS EXCHANGES]\nPROPOSER: {self._compact(proposer)}\nADVOCATE: {self._compact(advocate)}\nARBITRATOR: {self._compact(arbitrator)}"
            proposer = await self._proposer(llm, ctx_turn2)
            advocate = await self._advocate(llm, ctx_turn2, proposer)
            arbitrator = await self._arbitrator(llm, ctx_turn2, proposer, advocate)

        dur = int((time.time() - start) * 1000)
        escalated = arbitrator.get("final_confidence", 0) < ARBITRATOR_ESCALATION_THRESHOLD

        t = DebateTranscript(
            tenant_id=tenant_id, execution_id=execution_id, skill_id=skill.skill_id,
            tier_level=1, trigger_reason=reason,
            proposer_argument=proposer, advocate_argument=advocate, arbitrator_decision=arbitrator,
            debate_duration_ms=dur, escalated_to_hitl=escalated,
        )
        async with AsyncSessionLocal() as session:
            session.add(t)
            await session.commit()
            await session.refresh(t)

        logger.info(f"[Debate] {skill.skill_id}: decision={arbitrator.get('decision')}, conf={arbitrator.get('final_confidence',0):.2f}, {dur}ms")
        return t

    # Debate payloads used to be passed as `json.dumps(payload)[:800]`. Slicing a
    # serialized JSON string cuts mid-token and hands the next agent MALFORMED
    # JSON — the advocate would critique a truncated object, and the arbitrator
    # would weigh two broken ones. It degraded worst on exactly the long,
    # multi-step, compliance-heavy skills where the debate matters most.
    # Compact structurally instead: keep the shape, trim the values.
    _MAX_FIELD_CHARS = 600      # per string field
    _MAX_LIST_ITEMS = 8         # per evidence/risk array

    @classmethod
    def _compact(cls, payload: dict) -> str:
        """Serialize a debate payload, trimming values while keeping valid JSON."""
        def trim(v):
            if isinstance(v, str):
                return v if len(v) <= cls._MAX_FIELD_CHARS else v[: cls._MAX_FIELD_CHARS] + "…[trimmed]"
            if isinstance(v, list):
                out = [trim(x) for x in v[: cls._MAX_LIST_ITEMS]]
                if len(v) > cls._MAX_LIST_ITEMS:
                    out.append(f"…[{len(v) - cls._MAX_LIST_ITEMS} more omitted]")
                return out
            if isinstance(v, dict):
                return {k: trim(x) for k, x in v.items()}
            return v

        return json.dumps(trim(payload), default=str)

    def _build_context(self, skill: Skill, context: dict) -> str:
        steps = "\n".join(f"  Step {i+1}: {s.get('action','?')}" for i, s in enumerate(skill.steps or []))
        # intent is operator/signal-authored text that reaches every debate agent's
        # prompt. Fence it as data so a goal carrying "ignore your instructions..."
        # cannot re-steer the proposer/advocate/arbitrator (as missions/engine.py does).
        intent = prompt_guard.wrap_untrusted(context.get("intent", "N/A"))
        return f"SKILL: {skill.skill_id} | Dept: {skill.department} | Conf: {skill.confidence} ({skill.confidence_tier}) | Success: {skill.success_rate} over {skill.execution_count} runs | Tags: {skill.compliance_tags}\nSTEPS:\n{steps}\nINTENT: {intent}"

    async def _proposer(self, llm, ctx: str) -> dict:
        try:
            prompt = f"""You are the PROPOSER AGENT. Build an affirmative case for executing this action.
Provide minimum 3 evidence points grounded in the skill data. Cite specific numbers.

{ctx}

Respond in JSON: {{"evidence":["...","...","..."],"conclusion":"...","confidence":0.0-1.0,"grounded_in":["..."]}}"""
            # Short JSON verdict — cap generation with ample headroom (perf; a
            # well-formed response is far under this, so it never truncates).
            resp = await llm.complete(prompt=prompt, model_tier="reasoning", temperature=0.3, max_tokens=700)
            return self._parse_json(resp)
        except Exception as e:
            return {"evidence": [str(e)], "conclusion": "Error", "confidence": 0.3, "grounded_in": []}

    async def _advocate(self, llm, ctx: str, proposer: dict) -> dict:
        try:
            prompt = f"""You are the DEVIL'S ADVOCATE. Find flaws, risks, counter-evidence against this action.
Check if Proposer's claims are grounded. Identify edge cases and blast radius.

{ctx}

PROPOSER: {self._compact(proposer)}

Respond in JSON: {{"counter_evidence":["..."],"risks":["..."],"conclusion":"...","ungrounded_claims_found":0}}"""
            resp = await llm.complete(prompt=prompt, model_tier="reasoning", temperature=0.4, max_tokens=700)
            return self._parse_json(resp)
        except Exception as e:
            return {"counter_evidence": [str(e)], "risks": ["Analysis failed"], "conclusion": "Escalate", "ungrounded_claims_found": 0}

    async def _arbitrator(self, llm, ctx: str, proposer: dict, advocate: dict) -> dict:
        try:
            prompt = f"""You are the ARBITRATOR. Evaluate Proposer vs Advocate and render a decision.
>=0.7 confidence: PROCEED | 0.5-0.69: ESCALATE | <0.5: BLOCK

{ctx}

PROPOSER: {self._compact(proposer)}
ADVOCATE: {self._compact(advocate)}

Respond in JSON: {{"final_confidence":0.0-1.0,"rationale":"...","decision":"PROCEED|ESCALATE|BLOCK","weight_proposer":0.0-1.0,"weight_advocate":0.0-1.0}}"""
            resp = await llm.complete(prompt=prompt, model_tier="reasoning", temperature=0.2, max_tokens=500)
            result = self._parse_json(resp)
            c = result.get("final_confidence", 0.5)
            result["decision"] = "PROCEED" if c >= 0.7 else ("ESCALATE" if c >= 0.5 else "BLOCK")
            return result
        except Exception as e:
            return {"final_confidence": 0.0, "rationale": str(e), "decision": "ESCALATE", "weight_proposer": 0, "weight_advocate": 0}

    def _parse_json(self, response: str) -> dict:
        from app.services.json_utils import extract_json
        try:
            return extract_json(response)
        except (ValueError, json.JSONDecodeError):
            return {"error": "parse_failed", "raw": response[:300]}

    async def run_cross_domain_debate(self, topic: str, perspectives: list[str]) -> dict:
        """
        Runs a debate where multiple domain experts weigh in on an enterprise topic.
        Example: Finance vs Operations vs HR on "Handling Project X delay".
        """
        logger.info(f"[Debate] Cross-domain debate starting on '{topic}' with {perspectives}")

        # Perspectives are independent of each other - gather them concurrently
        # instead of paying one model round-trip per domain sequentially.
        import asyncio

        async def _position(p: str) -> str:
            prompt = f"You are the {p} perspective. Provide a 2-sentence position on: {topic}. Output JSON format: {{\"perspective\": \"...\", \"position\": \"...\"}}"
            try:
                resp = await self.llm.complete(prompt=prompt, model_tier="reasoning", temperature=0.3)
                return self._parse_json(resp).get("position", "Error generating position")
            except Exception as e:
                return str(e)

        positions = await asyncio.gather(*(_position(p) for p in perspectives))
        args = dict(zip(perspectives, positions))
                
        # Arbitrator synthesis
        arb_prompt = f"Synthesize these perspectives and provide a final recommendation for: {topic}\nPerspectives: {json.dumps(args)}\nOutput JSON: {{\"synthesis\": \"...\", \"recommendation\": \"...\"}}"
        try:
            arb_resp = await self.llm.complete(prompt=arb_prompt, model_tier="reasoning", temperature=0.2)
            arbitrator_result = self._parse_json(arb_resp)
        except Exception as e:
            arbitrator_result = {"synthesis": "Failed", "recommendation": "ESCALATE", "error": str(e)}
            
        return {
            "topic": topic,
            "perspectives_gathered": args,
            "arbitrator_synthesis": arbitrator_result
        }
