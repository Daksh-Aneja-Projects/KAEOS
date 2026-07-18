"""
KAEOS Sales Domain — CPQ Agent
"""
import logging
import json
from typing import Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.services.llm_router import LLMRouter
from app.sales.models.pipeline import Opportunity

logger = logging.getLogger(__name__)

class CPQAgent:
    """Agent for auditing configured quotes and processing discount approvals."""

    def __init__(self):
        self.router = LLMRouter()
        self.persona = "You are the KAEOS Sales Deal Desk auditor. Your task is reviewing requested discounts for margin preservation."

    async def evaluate_quote(self, db: AsyncSession, opportunity_id: str, requested_discount: float, tenant_id: str) -> Dict[str, Any]:
        """Audits custom deal structures and returns margin recommendations."""
        q = await db.execute(select(Opportunity).where(
            Opportunity.id == opportunity_id, Opportunity.tenant_id == tenant_id))
        opp = q.scalar_one_or_none()

        if not opp:
            raise ValueError(f"Opportunity {opportunity_id} not found")

        logger.info(f"CPQAgent auditing discount proposal of {requested_discount}% for opportunity: {opp.name}")

        prompt = f"""
        {self.persona}
        Evaluate if a discount rate of {requested_discount}% is acceptable for the opportunity details below.
        
        Opportunity: {opp.name}
        Stage: {opp.stage.value}
        Amount: ${opp.amount}
        
        Output JSON:
        {{
            "approved": true,
            "maximum_allowable_discount": 20.00,
            "margin_impact_summary": "Discount is within the acceptable 15% tier for enterprise deals over $100k.",
            "negotiation_counter": "Approve requested {requested_discount}% if customer signs multi-year commitment."
        }}
        """

        try:
            res = await self.router.complete(prompt=prompt, model_tier="reasoning")
            content = res if isinstance(res, str) else res.get("content", "{}")
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()

            analysis = json.loads(content)
            return analysis

        except Exception as e:
            logger.error(f"Sales CPQ deal desk review failed: {e}")
            raise
