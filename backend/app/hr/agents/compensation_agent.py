"""
KAEOS HR Vertical — Compensation Agent

Autonomous agent for managing compensation, equity, and market analysis.
"""
import logging
from typing import Dict, Any

from app.services.llm_router import LLMRouter

logger = logging.getLogger(__name__)

class CompensationAgent:
    """Agent for Compensation & Equity."""
    
    def __init__(self):
        self.router = LLMRouter()
        self.persona = "You are the KAEOS Compensation Agent. You analyze market data to ensure fair, competitive pay while strictly adhering to budget constraints."

    async def analyze_salary_band(self, job_title: str, location: str, current_band: Dict[str, float]) -> Dict[str, Any]:
        """Analyzes a salary band against market data."""
        logger.info(f"CompensationAgent analyzing salary band for {job_title} in {location}")
        
        # Fetch real market data from external intelligence service
        try:
            from app.services.external_intelligence import ExternalIntelligence
            market_data = await ExternalIntelligence.get_salary_benchmarks(job_title, location)
        except Exception as e:
            logger.warning(f"Failed to fetch market data: {e}")
            market_data = {"p25": current_band.get("min", 0), "p50": (current_band.get("min", 0) + current_band.get("max", 0)) / 2, "p75": current_band.get("max", 0)}
        
        prompt = f"""
        {self.persona}
        Analyze the current salary band against the market data.
        
        Job: {job_title}
        Location: {location}
        Current Band: {current_band}
        Market Data: {market_data}
        
        Provide a recommendation. Output JSON:
        {{
            "is_competitive": false,
            "recommended_band": {{"min": 115000, "max": 145000}},
            "reasoning": "Current band is below the 50th percentile for this location."
        }}
        """
        
        try:
            return await self.router.complete_json(prompt=prompt, model_tier="reasoning")
        except Exception as e:
            logger.error(f"CompensationAgent analysis failed: {e}")
            raise

    async def execute_via_pipeline(self, db, tenant_id: str, task_payload: dict) -> dict:
        """Execute this agent's task through the 7-gate SkillExecutionEngine pipeline.
        Ensures Compliance -> Fairness -> Confidence -> HITL -> Debate -> Execute -> Provenance."""
        from app.services.skill_executor import SkillExecutionEngine
        import uuid

        engine = SkillExecutionEngine()
        skill_def = {
            "skill_id": "hr_compensation_analysis",
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

