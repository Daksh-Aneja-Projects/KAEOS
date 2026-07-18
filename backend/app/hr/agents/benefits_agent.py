"""
KAEOS HR Vertical — Benefits Agent

Autonomous agent for managing benefits inquiries and enrollments.
"""
import logging

from app.services.llm_router import LLMRouter

logger = logging.getLogger(__name__)

class BenefitsAgent:
    """Agent for Benefits Administration."""
    
    def __init__(self):
        self.router = LLMRouter()
        self.persona = "You are the KAEOS Benefits Agent. You answer employee questions about health insurance, 401k, and perks based solely on the company policy."

    async def answer_benefits_query(self, employee_id: str, query: str, context_docs: str) -> str:
        """Answers an employee query using RAG over benefits documents."""
        logger.info(f"BenefitsAgent answering query for {employee_id}")
        
        prompt = f"""
        {self.persona}
        Answer the employee's question using ONLY the provided policy context.
        
        Policy Context:
        {context_docs}
        
        Employee Question:
        {query}
        
        If the answer is not in the context, politely state that you don't know and will escalate to a human specialist.
        """
        
        try:
            res = await self.router.complete(prompt=prompt, model_tier="fast")
            content = res if isinstance(res, str) else res.get("content", "")
            return content
            
        except Exception as e:
            logger.error(f"BenefitsAgent failed to answer query: {e}")
            return "I apologize, but I am currently unable to process your request. Please contact HR support."

    async def execute_via_pipeline(self, db, tenant_id: str, task_payload: dict) -> dict:
        """Execute this agent's task through the full 7-gate AgentExecutor pipeline
        (Compliance -> Fairness -> Confidence/HITL -> Debate -> Execute -> Audit)."""
        from app.hr.agents.gated_runner import run_gated_hr_skill

        steps = [
            {
                "id": "step_1",
                "action": "Answer the benefits task using only company policy; disclose the minimum necessary PHI",
                "tool": "none",
                "condition": "Always",
                "thresholds": "None",
            }
        ]
        return await run_gated_hr_skill(
            skill_id="hr_benefits_query",
            steps=steps,
            context={"task": task_payload, "persona": self.persona, "intent": "benefits task"},
            tenant_id=tenant_id,
            compliance_tags=["HIPAA", "GDPR"],
            requires_fairness=False,
        )

