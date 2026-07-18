"""KAEOS Sales Domain - Churn Prevention Agent

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


class ChurnAgent:
    async def identify_churn_risk(self, db: AsyncSession, account_id: str, tenant_id: str) -> Dict[str, Any]:
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
            "health_score": account.health_score,
        }
        facts = plain_facts(facts)
        return await run_gated_sales_skill(
            skill_id="sales_churn_prevention",
            steps=[{"step": 1, "name": "Assess",
                    "prompt": f"Assess churn risk for this account (low health score = high risk): {facts}"}],
            context={
                "account_id": account_id, "tenant_id": tenant_id, **facts,
                "instruction": "Output strict JSON: {churn_risk, drivers, retention_plan}.",
            },
            tenant_id=tenant_id,
        )
