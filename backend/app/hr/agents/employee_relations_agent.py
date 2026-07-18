"""
KAEOS HR Vertical — Employee Relations Agent

Autonomous agent for triaging ER cases and assessing risk.
"""
import logging
from typing import Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.services.llm_router import LLMRouter
from app.hr.models.employee_relations import ERCase, CaseSeverity

logger = logging.getLogger(__name__)

class EmployeeRelationsAgent:
    """Agent for ER Case Triage."""
    
    def __init__(self):
        self.router = LLMRouter()
        self.persona = "You are the KAEOS Employee Relations Agent. You triage sensitive employee complaints. Your role is to assess legal and compliance risk strictly, without taking sides."

    async def triage_case(self, db: AsyncSession, case_id: str) -> Dict[str, Any]:
        """Triages a newly opened ER case to assess severity and risk."""
        q = await db.execute(select(ERCase).where(ERCase.id == case_id))
        er_case = q.scalar_one_or_none()
        
        if not er_case:
            raise ValueError(f"ER Case {case_id} not found")
            
        logger.info(f"ER Agent triaging case {case_id}")
        
        # NOTE: the prompt is not built here — the gated runner composes it from
        # `context` below, which carries the same fields (see json_utils.compact_context).
        
        # Route through the full 7-gate AgentExecutor pipeline (ER cases are highly
        # compliance-sensitive: EEOC + GDPR, and Tier-1 debate engages via EEOC tag).
        from app.hr.agents.gated_runner import run_gated_hr_skill, extract_decision

        steps = [
            {
                "id": "triage_1",
                "action": "Triage the ER complaint for severity and compliance risk; output strict JSON with severity, risk_assessment, recommended_actions",
                "tool": "none",
                "condition": "Always",
                "thresholds": "None",
            }
        ]
        context = {
            "persona": self.persona,
            "case_title": er_case.title,
            "case_description": er_case.description,
            "intent": f"triage ER case {case_id}",
            "affected_entity_type": "Employee",
            "affected_count": 1,
            "instruction": "Output strict JSON in the decision field with keys: severity (LOW|MEDIUM|HIGH|CRITICAL), risk_assessment (string), recommended_actions (list).",
        }

        try:
            result = await run_gated_hr_skill(
                skill_id="hr_er_triage",
                steps=steps,
                context=context,
                tenant_id=er_case.tenant_id,
                compliance_tags=["EEOC", "GDPR"],
            )

            status = result.get("status")
            if status != "SUCCESS_CLEAN":
                logger.warning(f"ER Agent triage gated: {status} for {case_id}")
                return {
                    "status": status,
                    "gated": True,
                    "detail": {k: v for k, v in result.items() if k != "reasoning_chain"},
                }

            analysis = extract_decision(result) or {"severity": "MEDIUM", "risk_assessment": "", "recommended_actions": []}

            severity_map = {
                "LOW": CaseSeverity.LOW,
                "MEDIUM": CaseSeverity.MEDIUM,
                "HIGH": CaseSeverity.HIGH,
                "CRITICAL": CaseSeverity.CRITICAL,
            }
            er_case.severity = severity_map.get(analysis.get("severity", "MEDIUM"), CaseSeverity.MEDIUM)
            er_case.ai_risk_assessment = analysis.get("risk_assessment")
            er_case.ai_recommended_actions = analysis.get("recommended_actions", [])

            db.add(er_case)
            await db.commit()

            return analysis
        except Exception as e:
            logger.error(f"ER Agent triage failed: {e}")
            raise

    async def execute_via_pipeline(self, db, tenant_id: str, task_payload: dict) -> dict:
        """Execute this agent's task through the full 7-gate AgentExecutor pipeline
        (Compliance -> Fairness -> Confidence/HITL -> Debate -> Execute -> Audit)."""
        from app.hr.agents.gated_runner import run_gated_hr_skill

        steps = [
            {
                "id": "step_1",
                "action": "Assess the ER task for severity and compliance risk without taking sides",
                "tool": "none",
                "condition": "Always",
                "thresholds": "None",
            }
        ]
        return await run_gated_hr_skill(
            skill_id="hr_er_triage",
            steps=steps,
            context={"task": task_payload, "persona": self.persona, "intent": "ER task"},
            tenant_id=tenant_id,
            compliance_tags=["EEOC", "GDPR"],
        )

