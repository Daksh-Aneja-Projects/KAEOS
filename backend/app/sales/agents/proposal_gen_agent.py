"""KAEOS Sales Domain - Proposal Generation Agent

Context-grounding: the agent loads the real entity and reasons over its
content. Passing only an opaque id left the model classifying an identifier
(confirmed ungrounded on real onboarded data), so facts are non-optional.
"""
from typing import Any, Dict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.sales.agents.gated_runner import run_gated_sales_skill
from app.sales.models.accounts import Account
from app.sales.models.pipeline import Opportunity
from app.services.json_utils import plain_facts


def _v(x):
    return getattr(x, "value", x)


class ProposalGenAgent:
    async def generate_proposal(self, db: AsyncSession, opp_id: str, tenant_id: str) -> Dict[str, Any]:
        opp = (await db.execute(
            select(Opportunity).where(Opportunity.id == opp_id, Opportunity.tenant_id == tenant_id)
        )).scalar_one_or_none()
        if not opp:
            raise ValueError(f"Opportunity {opp_id} not found")

        account = None
        if opp.account_id:
            account = (await db.execute(
                select(Account).where(
                    Account.id == opp.account_id, Account.tenant_id == tenant_id)
            )).scalar_one_or_none()

        facts = {
            "opportunity_name": opp.name,
            "stage": _v(opp.stage),
            "amount": opp.amount,
            "close_date": str(opp.close_date) if opp.close_date else None,
            "account_name": account.name if account else None,
            "account_industry": account.industry if account else None,
        }
        facts = plain_facts(facts)
        return await run_gated_sales_skill(
            skill_id="sales_proposal_gen",
            steps=[{"step": 1, "name": "Generate",
                    "prompt": f"Draft a proposal outline for this opportunity: {facts}"}],
            context={
                "opp_id": opp_id, "tenant_id": tenant_id, **facts,
                "instruction": "Output strict JSON: {executive_summary, pricing_approach, key_terms}.",
            },
            tenant_id=tenant_id,
        )
