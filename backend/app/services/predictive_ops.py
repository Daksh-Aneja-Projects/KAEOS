"""
KAEOS 10X — Predictive Operations Engine (L20)
Latent Intent Recognition & Zero-Prompt Execution
"""
import logging
from typing import Optional
from datetime import datetime, timezone
import uuid

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.domain import Signal, Skill, SkillExecution
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
        
        # Fetch active skills to map against
        skills_q = await db.execute(select(Skill).where(Skill.status == "ACTIVE"))
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
            import json
            content = res if isinstance(res, str) else res.get("content", "{}")
            analysis = json.loads(content) if isinstance(content, str) else content
            
            if analysis.get("requires_action") and analysis.get("recommended_skill_id") in available_skills:
                return LatentIntent(
                    intent_type="AUTOMATED_PREDICTION",
                    confidence=analysis.get("confidence", 0.8),
                    recommended_skill_id=analysis["recommended_skill_id"],
                    context={
                        "source_signal": signal.id, 
                        "extracted_from": signal.source_type,
                        "llm_extracted_context": analysis.get("extracted_context", {})
                    }
                )
                
            return None
            
        except Exception as e:
            logger.error(f"Error in Latent Intent Analysis: {e}")
            return None

    @staticmethod
    async def trigger_zero_prompt_execution(db: AsyncSession, intent: LatentIntent) -> SkillExecution:
        """
        Takes a recognized latent intent and auto-queues a skill execution.
        """
        logger.info(f"Triggering Zero-Prompt Execution for skill {intent.recommended_skill_id}")
        
        # Locate the skill
        skill_q = await db.execute(select(Skill).where(Skill.skill_id == intent.recommended_skill_id))
        skill = skill_q.scalar_one_or_none()
        
        if not skill:
            raise ValueError(f"Skill {intent.recommended_skill_id} not found.")
            
        execution = SkillExecution(
            id=str(uuid.uuid4()),
            skill_db_id=skill.id,
            skill_id_name=skill.skill_id,
            tenant_id=skill.tenant_id,
            status="QUEUED",
            route_type="ZERO_PROMPT_AUTO",
            task_intent="Auto-predicted from latent intent analysis",
            context=intent.context,
            hitl_required=skill.confidence < 0.90,  # Requires human review if skill isn't highly confident
            started_at=datetime.now(timezone.utc)
        )
        
        db.add(execution)
        await db.commit()
        return execution

