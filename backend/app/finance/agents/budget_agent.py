"""KAEOS Finance Domain - Budget Variance Agent

Context-grounding: the agent loads the real entity and reasons over its
content. Passing only an opaque id left the model classifying an identifier
(confirmed ungrounded on real onboarded data), so facts are non-optional.
"""
from typing import Any, Dict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.finance.agents.gated_runner import run_gated_finance_skill
from app.finance.models.budgeting import Budget
from app.services.json_utils import plain_facts


def _v(x):
    return getattr(x, "value", x)


class BudgetAgent:
    # tenant_id is required with no default: a default silently falls back to
    # another tenant's data.
    async def analyze_variance(self, db: AsyncSession, budget_id: str, tenant_id: str, has_human_approver: bool = False) -> Dict[str, Any]:
        budget = (await db.execute(
            select(Budget).where(Budget.id == budget_id, Budget.tenant_id == tenant_id)
        )).scalar_one_or_none()
        if not budget:
            raise ValueError(f"Budget {budget_id} not found")

        facts = {
            "name": budget.name,
            "budget_type": _v(budget.budget_type),
            "fiscal_year": budget.fiscal_year,
            "department": budget.department,
            "status": _v(budget.status),
            "total_planned": budget.total_planned,
            "total_actual": budget.total_actual,
            "total_committed": budget.total_committed,
            "total_variance": budget.total_variance,
            "variance_pct": budget.variance_pct,
        }
        facts = plain_facts(facts)
        return await run_gated_finance_skill(
            skill_id="finance_budget_variance",
            steps=[{"step": 1, "name": "Analyze",
                    "prompt": f"Analyze the variance of this budget and identify drivers: {facts}"}],
            context={
                "budget_id": budget_id, "tenant_id": tenant_id, "has_human_approver": has_human_approver, **facts,
                "instruction": "Output strict JSON: {variance_severity, likely_drivers, recommended_action}.",
            },
            tenant_id=tenant_id,
        )
