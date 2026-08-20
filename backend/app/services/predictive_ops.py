"""
KAEOS 10X — Predictive Operations Engine (L20)
Latent Intent Recognition & Zero-Prompt Execution
"""
import logging
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.domain import Signal, Skill
from app.services.llm_router import LLMRouter

logger = logging.getLogger(__name__)

class LatentIntent:
    def __init__(self, intent_type: str, confidence: float, recommended_skill_id: str, context: dict):
        self.intent_type = intent_type
        self.confidence = confidence
        self.recommended_skill_id = recommended_skill_id
        self.context = context


class PredictiveOpsEngine:
    """
    Analyzes environmental signals (Slack, Email, Docs) and predicts tasks
    that need to be executed before a human explicitly requests them.
    """

    @staticmethod
    async def analyze_signal_for_intent(db: AsyncSession, signal: Signal) -> Optional[LatentIntent]:
        """
        Uses an LLM to evaluate if a newly ingested signal implies a task that should be executed.
        """
        logger.info(f"Predictive Ops evaluating signal {signal.id} ({signal.signal_type}) for latent intent.")
        
        # Fetch active skills to map against - this tenant's only. Unscoped,
        # every tenant's skill catalog leaked into the prompt and the intent
        # could recommend (and later execute) another tenant's skill.
        skills_q = await db.execute(select(Skill).where(
            Skill.status == "ACTIVE", Skill.tenant_id == signal.tenant_id))
        available_skills = {s.skill_id: s.domain for s in skills_q.scalars().all()}
        
        if not available_skills:
            return None

        prompt = f"""
        You are the KAEOS Latent Intent Engine.
        Analyze the following signal and determine if it implicitly requires any of our available skills to be executed.
        
        Signal Payload:
        {signal.clean_payload}
        
        Available Skills:
        {available_skills}
        
        Respond with a JSON object:
        {{
            "requires_action": true/false,
            "recommended_skill_id": "skill_id_here",
            "confidence": 0.0-1.0,
            "extracted_context": {{...}}
        }}
        """
        
        try:
            router = LLMRouter()
            res = await router.complete(prompt=prompt, model_tier="fast")
            from app.services.json_utils import extract_json_object
            content = res if isinstance(res, str) else res.get("content", "{}")
            analysis = extract_json_object(content) if isinstance(content, str) else content

            if analysis.get("requires_action") and analysis.get("recommended_skill_id") in available_skills:
                return LatentIntent(
                    intent_type="AUTOMATED_PREDICTION",
                    confidence=analysis.get("confidence", 0.8),
                    recommended_skill_id=analysis["recommended_skill_id"],
                    context={
                        "source_signal": signal.id,
                        "tenant_id": signal.tenant_id,
                        "extracted_from": signal.source_type,
                        "llm_extracted_context": analysis.get("extracted_context", {})
                    }
                )
                
            return None
            
        except Exception as e:
            logger.error(f"Error in Latent Intent Analysis: {e}")
            return None

    @staticmethod
    async def trigger_zero_prompt_execution(db: AsyncSession, intent: LatentIntent) -> str:
        """Enqueue a recognized latent intent for GOVERNED execution.

        Historically this wrote a SkillExecution row stamped ``QUEUED`` — a
        status no gate produces — that nothing ever drained, so the "queued"
        run never ran, yet the row was metered for billing and diluted the
        safe-autonomy denominator. It now enqueues a durable job whose handler
        runs the skill through the full gate pipeline (see
        job_handlers._run_zero_prompt_execution); the SkillExecution row that
        eventually exists is a real, gated one. Returns the job id.
        """
        logger.info(f"Enqueuing zero-prompt execution for skill {intent.recommended_skill_id}")

        # Locate the skill - in the signal's tenant only (skill names are
        # unique per tenant, and the execution runs under skill.tenant_id).
        stmt = select(Skill).where(Skill.skill_id == intent.recommended_skill_id)
        if intent.context.get("tenant_id"):
            stmt = stmt.where(Skill.tenant_id == intent.context["tenant_id"])
        skill_q = await db.execute(stmt)
        skill = skill_q.scalars().first()

        if not skill:
            raise ValueError(f"Skill {intent.recommended_skill_id} not found.")

        from app.services import job_queue
        return await job_queue.enqueue(
            db, skill.tenant_id, "zero_prompt_execution",
            payload={
                "skill_db_id": skill.id,
                "skill_id": skill.skill_id,
                "tenant_id": skill.tenant_id,
                "intent_confidence": intent.confidence,
                "context": intent.context,
            },
        )

