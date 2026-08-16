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

    async def _fetch_market_data(self, job_title: str, location: str, current_band: Dict[str, float]) -> Dict[str, Any]:
        """Real market benchmarks from the external intelligence service, with a
        band-derived fallback when it is unavailable. Shared by the direct
        analysis and the gated pipeline so both reason over the same data."""
        try:
            from app.services.external_intelligence import ExternalIntelligence
            return await ExternalIntelligence.get_salary_benchmarks(job_title, location)
        except Exception as e:
            logger.warning(f"Failed to fetch market data: {e}")
            return {"p25": current_band.get("min", 0),
                    "p50": (current_band.get("min", 0) + current_band.get("max", 0)) / 2,
                    "p75": current_band.get("max", 0)}

    async def analyze_salary_band(self, job_title: str, location: str, current_band: Dict[str, float]) -> Dict[str, Any]:
        """Analyzes a salary band against market data."""
        logger.info(f"CompensationAgent analyzing salary band for {job_title} in {location}")

        market_data = await self._fetch_market_data(job_title, location, current_band)

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
        """Execute salary-band analysis through the full 7-gate AgentExecutor
        pipeline (Compliance -> Fairness -> Confidence/HITL -> Debate -> Execute
        -> Audit). Market data is fetched here and handed to the gated reasoning
        step; the caller reads the decision from the returned result."""
        from app.hr.agents.gated_runner import run_gated_hr_skill

        job_title = task_payload.get("job_title", "")
        location = task_payload.get("location", "Remote")
        current_band = task_payload.get("current_band", {})
        market_data = await self._fetch_market_data(job_title, location, current_band)
        steps = [
            {
                "id": "comp_1",
                "action": "Compare the current salary band against market data and recommend a fair, competitive band; output strict JSON with is_competitive, recommended_band, reasoning",
                "tool": "none",
                "condition": "Always",
                "thresholds": "None",
            }
        ]
        return await run_gated_hr_skill(
            skill_id="hr_compensation_analysis",
            steps=steps,
            context={
                "persona": self.persona,
                "job_title": job_title,
                "location": location,
                "current_band": current_band,
                "market_data": market_data,
                "intent": "analyze salary band against market",
                # Pay decisions touch protected attributes - score for bias.
                "affected_entity_type": "Employee",
                "affected_count": 1,
                # GDPR Gate-6 audit basis: compensation administration is
                # processing for the performance of the employment contract.
                "legal_basis": "contract:compensation_administration",
                "instruction": "Output strict JSON in the decision field with keys: is_competitive (bool), recommended_band (object with min and max), reasoning (string).",
            },
            tenant_id=tenant_id,
            compliance_tags=["EEOC"],
            requires_fairness=True,
        )

