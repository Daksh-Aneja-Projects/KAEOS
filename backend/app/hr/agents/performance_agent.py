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
            from app.services.json_utils import extract_json_object
            content = res if isinstance(res, str) else res.get("content", "{}")
            analysis = extract_json_object(content)

            review.ai_feedback_summary = analysis.get("summary")
            review.ai_growth_areas = analysis.get("growth_areas", [])
            db.add(review)
            await db.commit()
            
            return analysis
        except Exception as e:
            logger.error(f"PerformanceAgent synthesis failed: {e}")
            raise

    async def execute_via_pipeline(self, db, tenant_id: str, task_payload: dict) -> dict:
        """Execute 360-feedback synthesis through the full 7-gate AgentExecutor
        pipeline (Compliance -> Fairness -> Confidence/HITL -> Debate -> Execute
        -> Audit). The caller persists the returned decision onto the review."""
        from app.hr.agents.gated_runner import run_gated_hr_skill

        steps = [
            {
                "id": "synth_1",
                "action": "Synthesize the peer feedback into a constructive, bias-free summary; output strict JSON with strengths, growth_areas, summary, suggested_rating",
                "tool": "none",
                "condition": "Always",
                "thresholds": "None",
            }
        ]
        return await run_gated_hr_skill(
            skill_id="hr_performance_synthesis",
            steps=steps,
            context={
                "persona": self.persona,
                "task": task_payload,
                "intent": "synthesize 360 performance feedback",
                # A rating decision touches protected attributes - score for bias.
                "affected_entity_type": "Employee",
                "affected_count": 1,
                "legal_basis": "legitimate_interests:performance_management",
                "instruction": "Output strict JSON in the decision field with keys: strengths (list), growth_areas (list), summary (string), suggested_rating (integer 1-5). Remove biased language.",
            },
            tenant_id=tenant_id,
            compliance_tags=["EEOC", "GDPR"],
            requires_fairness=True,
        )

