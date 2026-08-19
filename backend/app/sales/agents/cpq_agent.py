"""
KAEOS Sales Domain — CPQ Agent

Discount/margin approval is a financial control, same class as Finance's AP
agent (app/finance/agents/ap_agent.py). It routes through the full 7-gate
pipeline (Compliance -> Fairness -> Confidence/HITL -> Debate -> Execute ->
Audit) tagged SOX, so a discount is never rubber-stamped outside governance.
"""
import logging
from typing import Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.sales.agents.gated_runner import run_gated_sales_skill, extract_decision
from app.sales.models.pipeline import Opportunity
from app.services.json_utils import enum_value, plain_facts

logger = logging.getLogger(__name__)


class CPQAgent:
    """Agent for auditing configured quotes and processing discount approvals."""

    persona = "You are the KAEOS Sales Deal Desk auditor. Your task is reviewing requested discounts for margin preservation."

    async def evaluate_quote(self, db: AsyncSession, opportunity_id: str, requested_discount: float, tenant_id: str) -> Dict[str, Any]:
        """Audits a custom deal structure through the gated pipeline and returns margin recommendations."""
        q = await db.execute(select(Opportunity).where(
            Opportunity.id == opportunity_id, Opportunity.tenant_id == tenant_id))
        opp = q.scalar_one_or_none()

        if not opp:
            raise ValueError(f"Opportunity {opportunity_id} not found")

        logger.info(f"CPQAgent auditing discount proposal of {requested_discount}% for opportunity: {opp.name}")

        facts = {
            "opportunity_name": opp.name,
            "stage": enum_value(opp.stage),
            "amount": float(opp.amount or 0),
            "requested_discount_pct": requested_discount,
        }
        facts = plain_facts(facts)
        steps = [{
            "step": 1, "name": "Evaluate Discount",
            "prompt": f"""
            {self.persona}
            Evaluate if a discount rate of {requested_discount}% is acceptable for the opportunity details below.

            Opportunity details: {facts}

            Output JSON:
            {{
                "approved": true,
                "maximum_allowable_discount": 20.00,
                "margin_impact_summary": "Discount is within the acceptable 15% tier for enterprise deals over $100k.",
                "negotiation_counter": "Approve requested {requested_discount}% if customer signs multi-year commitment."
            }}
            """,
        }]

        result = await run_gated_sales_skill(
            skill_id="sales_cpq_discount_review",
            steps=steps,
            context={
                "opportunity_id": opportunity_id, "tenant_id": tenant_id, **facts,
                # SOX Gate-6 audit fact: the deal value under review.
                "amount": float(opp.amount or 0),
                "instruction": "Output strict JSON: {approved, maximum_allowable_discount, margin_impact_summary, negotiation_counter}.",
            },
            tenant_id=tenant_id,
            # A discount/margin decision is a financial control, not a personal-
            # data one: SOX applies, GDPR does not.
            compliance_tags=["SOX"],
        )

        if result.get("status") == "SUCCESS_CLEAN":
            decision = extract_decision(result)
            return {
                "status": "SUCCESS_CLEAN",
                "approved": decision.get("approved"),
                "maximum_allowable_discount": decision.get("maximum_allowable_discount"),
                "margin_impact_summary": decision.get("margin_impact_summary"),
                "negotiation_counter": decision.get("negotiation_counter"),
                "execution_id": result.get("execution_id"),
                "reasoning_chain": result.get("reasoning_chain", []),
            }

        if result.get("status") == "PENDING_HITL":
            logger.info(f"CPQAgent: quote for {opportunity_id} awaiting human approval (PENDING_HITL)")
            return {
                "status": "PENDING_HITL",
                "execution_id": result.get("execution_id"),
                "reason": "This discount needs human review before it is approved.",
            }

        if result.get("status") in ("BLOCKED_COMPLIANCE", "BLOCKED_FAIRNESS", "BLOCKED_DEBATE"):
            logger.warning(f"CPQAgent: quote for {opportunity_id} blocked by gate: {result.get('status')}")
            return result

        logger.error(f"CPQAgent: quote review for {opportunity_id} failed with status {result.get('status')}")
        return result
