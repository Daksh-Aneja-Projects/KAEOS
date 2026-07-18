"""KAEOS Support Domain - CSAT Analysis Agent

Context-grounding: the agent loads real records and reasons over their
content. Passing only opaque ids left the model reasoning over identifiers
(confirmed ungrounded on real onboarded data), so facts are non-optional.
"""
from typing import Any, Dict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.support.agents.gated_runner import run_gated_support_skill
from app.support.models.feedback import CustomerSatisfaction, NPS_Survey
from app.services.json_utils import plain_facts


class CSATAgent:
    async def analyze_surveys(self, db: AsyncSession, survey_batch_id: str, tenant_id: str) -> Dict[str, Any]:
        # CSAT surveys are CustomerSatisfaction rows (post-ticket); NPS rows
        # are also accepted so either feedback source can be analyzed.
        csat = (await db.execute(
            select(CustomerSatisfaction).where(
                CustomerSatisfaction.id == survey_batch_id,
                CustomerSatisfaction.tenant_id == tenant_id,
            )
        )).scalar_one_or_none()
        if csat:
            facts = {
                "rating_1_to_5": csat.rating,
                "comment": (csat.comment or "")[:1200],
                "recorded_sentiment": csat.sentiment,
            }
        else:
            nps = (await db.execute(
                select(NPS_Survey).where(
                    NPS_Survey.id == survey_batch_id,
                    NPS_Survey.tenant_id == tenant_id,
                )
            )).scalar_one_or_none()
            if not nps:
                raise ValueError(f"Survey {survey_batch_id} not found")
            facts = {
                "nps_score_0_to_10": nps.score,
                "feedback_text": (nps.feedback_text or "")[:1200],
            }
        facts = plain_facts(facts)
        return await run_gated_support_skill(
            skill_id="support_csat_analysis",
            steps=[{"step": 1, "name": "Analyze",
                    "prompt": f"Analyze this customer satisfaction survey: {facts}"}],
            context={
                "batch_id": survey_batch_id, "tenant_id": tenant_id, **facts,
                "instruction": "Output strict JSON: {sentiment, themes, follow_up_needed}.",
            },
            tenant_id=tenant_id,
        )
