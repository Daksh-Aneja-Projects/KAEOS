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
            from app.services.json_utils import extract_json_object
            content = res if isinstance(res, str) else res.get("content", "{}")
            return extract_json_object(content)
        except Exception as e:
            logger.error(f"OffboardingAgent analysis failed: {e}")
            raise

    async def execute_via_pipeline(self, db, tenant_id: str, task_payload: dict) -> dict:
        """Execute exit-interview analysis through the full 7-gate AgentExecutor
        pipeline (Compliance -> Fairness -> Confidence/HITL -> Debate -> Execute
        -> Audit). Advisory analysis only: the real offboarding actions (access
        revocation, equipment return, final pay) stay human tasks on the plan,
        so the skill id deliberately avoids the high-consequence 'offboarding'
        tag that would force every summary to a human."""
        from app.hr.agents.gated_runner import run_gated_hr_skill

        steps = [
            {
                "id": "exit_1",
                "action": "Analyze the exit-interview responses for reasons for leaving and systemic risks; output strict JSON with primary_reason_for_leaving, systemic_risks, manager_feedback_summary, sentiment",
                "tool": "none",
                "condition": "Always",
                "thresholds": "None",
            }
        ]
        return await run_gated_hr_skill(
            skill_id="hr_exit_interview_analysis",
            steps=steps,
            context={
                "persona": self.persona,
                "task": task_payload,
                "intent": "analyze exit interview",
                "legal_basis": "legitimate_interests:offboarding_analysis",
                "instruction": "Output strict JSON in the decision field with keys: primary_reason_for_leaving (string), systemic_risks (list), manager_feedback_summary (string), sentiment (number from -1 to 1).",
            },
            tenant_id=tenant_id,
            compliance_tags=["GDPR"],
            requires_fairness=False,
        )


if __name__ == "__main__":
    # HR4 invariant: auto-running the exit interview must never complete a fresh
    # offboarding plan by itself. The on-the-fly plan seeds the standard task
    # list (revoke access, return equipment, final pay, exit interview), so
    # completing only the interview leaves real work outstanding and the plan
    # stays ACTIVE. The old bug seeded total_tasks=0, then the single interview
    # task made done (1) >= total (1) and wrongly flipped the plan to COMPLETED.
    def _plan_completed(total_tasks: int, done: int) -> bool:
        return bool(total_tasks) and done >= total_tasks

    assert _plan_completed(4, 1) is False, "fresh seeded plan, only interview done -> must stay ACTIVE"
    assert _plan_completed(4, 4) is True, "all offboarding tasks done -> COMPLETED"
    assert _plan_completed(0, 0) is False, "empty plan is not complete (the old auto-complete trap)"
    print("offboarding_agent self-check passed")

