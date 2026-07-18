"""
KAEOS HR Vertical — Offboarding Agent

Autonomous agent for managing employee departures safely and compliantly.
"""
import logging
from typing import Dict, Any

from app.services.llm_router import LLMRouter

logger = logging.getLogger(__name__)

class OffboardingAgent:
    """Agent for Employee Offboarding."""
    
    def __init__(self):
        self.router = LLMRouter()
        self.persona = "You are the KAEOS Offboarding Agent. Your priority is to ensure a smooth transition, secure company assets, and conduct objective exit interviews."

    async def analyze_exit_interview(self, employee_id: str, survey_responses: Dict[str, str]) -> Dict[str, Any]:
        """Analyzes exit interview feedback for actionable organizational insights."""
        logger.info(f"OffboardingAgent analyzing exit interview for {employee_id}")
        
        prompt = f"""
        {self.persona}
        Analyze the following exit interview responses. Identify the core reasons for leaving and any systemic issues in the organization.
        
        Responses:
        {survey_responses}
        
        Output JSON:
        {{
            "primary_reason_for_leaving": "Compensation",
            "systemic_risks": ["Burnout in the engineering team", "Lack of clear career progression"],
            "manager_feedback_summary": "Positive but noted lack of 1:1 frequency.",
            "sentiment": 0.4
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
                
            return json.loads(content)
        except Exception as e:
            logger.error(f"OffboardingAgent analysis failed: {e}")
            raise

    async def execute_via_pipeline(self, db, tenant_id: str, task_payload: dict) -> dict:
        """Execute this agent's task through the 7-gate SkillExecutionEngine pipeline.
        Ensures Compliance -> Fairness -> Confidence -> HITL -> Debate -> Execute -> Provenance."""
        from app.services.skill_executor import SkillExecutionEngine
        import uuid

        engine = SkillExecutionEngine()
        skill_def = {
            "skill_id": "hr_offboarding_checklist",
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

