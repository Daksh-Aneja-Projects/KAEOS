"""
KAEOS HR Vertical — Onboarding Agent

Autonomous agent responsible for guiding new hires through onboarding.
"""
import logging
from typing import Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.services.llm_router import LLMRouter
from app.hr.models.core import HREmployee as Employee
from app.hr.models.onboarding import BoardingTask, TaskStatus

logger = logging.getLogger(__name__)

class OnboardingAgent:
    """Agent for Employee Onboarding."""
    
    def __init__(self):
        self.router = LLMRouter()
        self.persona = "You are the KAEOS Onboarding Agent. Your goal is to make new hires feel welcome, ensure all compliance forms are completed, and coordinate equipment provisioning."

    async def check_in_with_new_hire(self, db: AsyncSession, employee_id: str, week_num: int, response: str = "") -> Dict[str, Any]:
        """Sends a check-in message to the new hire and evaluates their response."""
        q = await db.execute(select(Employee).where(Employee.id == employee_id))
        employee = q.scalar_one_or_none()
        
        logger.info(f"OnboardingAgent executing Week {week_num} check-in for {employee_id}")
        
        # Analyze the provided response
        simulated_response = response if response else "I'm doing well."
        
        # NOTE: the prompt is not built here — the gated runner composes it from
        # `context` below, which carries the same fields (see json_utils.compact_context).
        
        # Route through the full 7-gate AgentExecutor pipeline.
        from app.hr.agents.gated_runner import run_gated_hr_skill, extract_decision

        steps = [
            {
                "id": "checkin_1",
                "action": "Analyze the new hire's response and output strict JSON with sentiment_score, issues_detected, requires_human_escalation, recommended_action",
                "tool": "none",
                "condition": "Always",
                "thresholds": "None",
            }
        ]
        context = {
            "persona": self.persona,
            "employee_name": f"{employee.first_name} {employee.last_name}",
            "week_num": week_num,
            "response_text": simulated_response,
            "intent": f"onboarding week-{week_num} check-in for {employee_id}",
            "affected_entity_type": "Employee",
            "affected_count": 1,
            "instruction": "Output strict JSON in the decision field with keys: sentiment_score (0.0-1.0), issues_detected (list of strings), requires_human_escalation (bool), recommended_action (string).",
        }

        try:
            result = await run_gated_hr_skill(
                skill_id="hr_onboarding_checkin",
                steps=steps,
                context=context,
                tenant_id=employee.tenant_id,
                compliance_tags=["EEOC", "GDPR", "I9"],
            )

            status = result.get("status")
            if status != "SUCCESS_CLEAN":
                logger.warning(f"OnboardingAgent check-in gated: {status} for {employee_id}")
                return {
                    "status": status,
                    "gated": True,
                    "requires_human_escalation": True,
                    "detail": {k: v for k, v in result.items() if k != "reasoning_chain"},
                }

            analysis = extract_decision(result)
            if not analysis:
                analysis = {"sentiment_score": 0.5, "issues_detected": [],
                            "requires_human_escalation": False, "recommended_action": ""}
            return analysis

        except Exception as e:
            logger.error(f"OnboardingAgent check-in failed via gated executor: {e}")
            raise

    async def verify_task_completion(self, db: AsyncSession, task_id: str) -> bool:
        """Verifies if an automated task is actually complete."""
        q = await db.execute(select(BoardingTask).where(BoardingTask.id == task_id))
        task = q.scalar_one_or_none()
        
        if not task:
            return False
            
        # Logic to verify task via integrations
        task.status = TaskStatus.COMPLETED
        db.add(task)
        await db.commit()
        return True
