"""KAEOS Sales Domain - Account Health Agent

Context-grounding: the agent loads the real entity and reasons over its
content. Passing only an opaque id left the model classifying an identifier
(confirmed ungrounded on real onboarded data), so facts are non-optional.
"""
from typing import Any, Dict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.sales.agents.gated_runner import run_gated_sales_skill
from app.sales.models.accounts import Account
from app.services.json_utils import plain_facts


class AccountHealthAgent:
    async def assess_health(self, db: AsyncSession, account_id: str, tenant_id: str) -> Dict[str, Any]:
        account = (await db.execute(
            select(Account).where(Account.id == account_id, Account.tenant_id == tenant_id)
        )).scalar_one_or_none()
        if not account:
            raise ValueError(f"Account {account_id} not found")

        facts = {
            "name": account.name,
            "industry": account.industry,
            "employee_count": account.employee_count,
            "annual_recurring_revenue": account.annual_recurring_revenue,
            "current_health_score": account.health_score,
        }
        facts = plain_facts(facts)
        return await run_gated_sales_skill(
            skill_id="sales_account_health",
            steps=[{"step": 1, "name": "Assess",
                    "prompt": f"Assess the health of this account from its profile: {facts}"}],
            context={
                "account_id": account_id, "tenant_id": tenant_id, **facts,
                "instruction": "Output strict JSON: {health_assessment, risk_signals, engagement_actions}.",
            },
            tenant_id=tenant_id,
        )
