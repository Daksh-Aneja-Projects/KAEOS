"""
KAEOS HR Vertical — Performance Agent

Autonomous agent for managing performance cycles and feedback synthesis.
"""
import logging
from typing import Dict, Any, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.services.llm_router import LLMRouter
from app.hr.models.performance import PerformanceReview

logger = logging.getLogger(__name__)

class PerformanceAgent:
    """Agent for Performance Management."""
    
    def __init__(self):
        self.router = LLMRouter()
        self.persona = "You are the KAEOS Performance Agent. You help managers summarize 360-degree feedback objectively and without bias to create constructive performance reviews."

    async def synthesize_feedback(self, db: AsyncSession, review_id: str, raw_feedback: List[str]) -> Dict[str, Any]:
        """Synthesizes raw 360 feedback into actionable insights."""
        q = await db.execute(select(PerformanceReview).where(PerformanceReview.id == review_id))
        review = q.scalar_one_or_none()
        
        if not review:
            raise ValueError(f"Review {review_id} not found")
            
        logger.info(f"PerformanceAgent synthesizing feedback for review {review_id}")
        
        feedback_text = "\\n- ".join(raw_feedback)
        
        prompt = f"""
        {self.persona}
        Synthesize the following peer feedback into a constructive summary for the employee's manager.
        Remove any biased language. Focus on actionable themes.
        
        Raw Feedback:
        - {feedback_text}
        
        Output JSON:
        {{
            "strengths": ["...", "..."],
            "growth_areas": ["...", "..."],
            "summary": "...",
            "suggested_rating": 4
        }}
        """
        
        try:
            res = await self.router.complete(prompt=prompt, model_tier="reasoning")
            import json
            content = res if isinstance(res, str) else res.get("content", "{}")
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()
                
            analysis = json.loads(content)
            
            review.ai_feedback_summary = analysis.get("summary")
            review.ai_growth_areas = analysis.get("growth_areas", [])
            db.add(review)
            await db.commit()
            
            return analysis
        except Exception as e:
            logger.error(f"PerformanceAgent synthesis failed: {e}")
            raise

    async def execute_via_pipeline(self, db, tenant_id: str, task_payload: dict) -> dict:
        """Execute this agent's task through the 7-gate SkillExecutionEngine pipeline.
        Ensures Compliance -> Fairness -> Confidence -> HITL -> Debate -> Execute -> Provenance."""
        from app.services.skill_executor import SkillExecutionEngine
        import uuid

        engine = SkillExecutionEngine()
        skill_def = {
            "skill_id": "hr_performance_synthesis",
            "department": "hr",
            "steps": [
                {
                    "id": "step_1",
                    "action": "Execute the HR task described in the context",
                    "tool": "none",
                    "condition": "Always",
                    "thresholds": "None"
                }
            ]
        }
        execution_id = str(uuid.uuid4())
        return await engine.execute(
            db=db,
            tenant_id=tenant_id,
            skill=skill_def,
            context={
                "task": task_payload,
                "persona": self.persona,
            },
            execution_id=execution_id,
            route_type="HR_AGENT",
        )

