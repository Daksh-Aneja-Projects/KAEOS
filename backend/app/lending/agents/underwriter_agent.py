"""
KAEOS Lending Domain - Underwriter Agent

Makes the credit decision. The BINDING decision is the deterministic policy
evaluation with REAL fail-closed compliance gates (see
app/lending/services/underwriting.py); this agent routes the action through the
7-gate governance pipeline first (compliance / fairness / HITL / debate) and
only persists the decision on a clean gate pass. The LLM produces a
plain-English rationale for the reviewer - it never changes the decision.
"""
import logging
from typing import Any, Dict, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.lending.agents.gated_runner import extract_decision, run_gated_lending_skill
from app.lending.models.core import CreditPolicy, LoanApplication, LoanStatus
from app.lending.services.underwriting import (evaluate_policy,
                                               underwrite_application)
from app.models.execution_status import ExecutionStatus

logger = logging.getLogger(__name__)


class UnderwriterAgent:
    def __init__(self):
        self.persona = (
            "You are the KAEOS Underwriter Agent. You explain a deterministic "
            "credit decision in plain English for a human reviewer. You never "
            "override the policy engine and never introduce a prohibited basis."
        )

    async def fair_lending_scan(self, db: AsyncSession, tenant_id: str) -> Dict[str, Any]:
        """Run the deterministic four-fifths disparate-impact scan over real
        decided applications - the same computation /lending/analytics reports.
        No LLM involved; returns an honest NO_DATA status when no decided
        applications carry protected-class data."""
        from app.lending.services.analytics import fair_lending_ratios
        fair = await fair_lending_ratios(db, tenant_id)
        if fair is None:
            return {"status": "NO_DATA",
                    "message": ("Fair-lending scan needs decided applications "
                                "with protected-class data; none available yet.")}
        return {"status": "success", "four_fifths": fair}

    async def underwrite(
        self, db: AsyncSession, application_id: str, tenant_id: str, *,
        decided_by: str,
        approval_cohorts: Optional[dict] = None,
        business_necessity: Optional[str] = None,
    ) -> Dict[str, Any]:
        app_q = await db.execute(select(LoanApplication).where(
            LoanApplication.id == application_id,
            LoanApplication.tenant_id == tenant_id))
        app = app_q.scalar_one_or_none()
        if not app:
            raise ValueError(f"Loan application {application_id} not found")

        pol_q = await db.execute(select(CreditPolicy).where(
            CreditPolicy.tenant_id == tenant_id,
            CreditPolicy.product == app.product))
        policy = pol_q.scalar_one_or_none()
        verdict = evaluate_policy(app, policy)

        steps = [{
            "step": 1,
            "name": "Explain Underwriting Decision",
            "prompt": (
                f"A deterministic credit-policy engine reached the decision "
                f"'{verdict['decision']}' on application {app.application_number} "
                f"for the reasons:\n"
                + ("\n".join(f"- {r}" for r in verdict['reasons']) or "- All policy thresholds met.")
                + "\nWrite a short, specific, plain-English explanation for the "
                "human reviewer. Do not reference race, sex, age, national origin, "
                "or any prohibited basis. Return JSON "
                "{\"rationale\": str, \"confidence\": number}."),
        }]

        context = {
            "application_id": app.id,
            "decision": verdict["decision"],
            "reasons": verdict["reasons"],
            "amount": float(app.amount or 0),
            "approval_cohorts": approval_cohorts,
            "business_necessity": business_necessity,
            "has_human_approver": bool(decided_by),
        }

        result = await run_gated_lending_skill(
            skill_id="lending_underwrite", steps=steps, context=context,
            tenant_id=tenant_id, confidence=0.9)

        status = result.get("status")
        if status == ExecutionStatus.PENDING_HITL:
            app.status = LoanStatus.PENDING_HITL.value
            db.add(app)
            await db.commit()
            return {"status": ExecutionStatus.PENDING_HITL, "application_id": app.id,
                    "execution_id": result.get("execution_id"),
                    "reason": "Underwriting decision requires human approval."}

        if status in (ExecutionStatus.BLOCKED_COMPLIANCE, "BLOCKED_FAIRNESS", ExecutionStatus.BLOCKED_DEBATE):
            logger.warning("UnderwriterAgent: %s blocked by %s", application_id, status)
            return result

        # Clean gate pass -> persist the binding decision through the REAL
        # fail-closed underwriting gates (with cohort/business-necessity data).
        decision_row = await underwrite_application(
            db, tenant_id, application_id=app.id, decided_by=decided_by,
            approval_cohorts=approval_cohorts, business_necessity=business_necessity)

        rationale = extract_decision(result)
        return {
            "status": "success",
            "application_id": app.id,
            "decision": decision_row.decision,
            "reasons": decision_row.reasons,
            "rationale": rationale.get("rationale"),
            "decision_id": decision_row.id,
            "execution_id": result.get("execution_id"),
        }
