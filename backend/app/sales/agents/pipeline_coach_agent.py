"""KAEOS Sales Domain - Pipeline Coach Agent

Context-grounding: the agent loads the real entity and reasons over its
content. Passing only an opaque id left the model classifying an identifier
(confirmed ungrounded on real onboarded data), so facts are non-optional.
"""
from typing import Any, Dict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.sales.agents.gated_runner import run_gated_sales_skill
from app.sales.models.pipeline import Opportunity
from app.services.json_utils import plain_facts


def _v(x):
    return getattr(x, "value", x)


class PipelineCoachAgent:
    async def coach_opportunity(self, db: AsyncSession, opp_id: str, tenant_id: str) -> Dict[str, Any]:
        opp = (await db.execute(
            select(Opportunity).where(Opportunity.id == opp_id, Opportunity.tenant_id == tenant_id)
        )).scalar_one_or_none()
        if not opp:
            raise ValueError(f"Opportunity {opp_id} not found")

        facts = {
            "name": opp.name,
            "stage": _v(opp.stage),
            "amount": opp.amount,
            "probability": opp.probability,
            "close_date": str(opp.close_date) if opp.close_date else None,
            "ai_win_probability": opp.ai_win_probability,
            "stalled": opp.ai_stalled_flag,
            "prior_next_step": opp.ai_next_step,
        }
        facts = plain_facts(facts)
        return await run_gated_sales_skill(
            skill_id="sales_pipeline_coach",
            steps=[{"step": 1, "name": "Coach",
                    "prompt": f"Coach the rep on advancing this opportunity: {facts}"}],
            context={
                "opp_id": opp_id, "tenant_id": tenant_id, **facts,
                "instruction": "Output strict JSON: {next_step, risk_flags, win_probability_assessment}.",
            },
            tenant_id=tenant_id,
        )
