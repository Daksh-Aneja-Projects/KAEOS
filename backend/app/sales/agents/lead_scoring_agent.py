"""KAEOS Sales Domain - Lead Scoring Agent

Context-grounding: the agent loads the real entity and reasons over its
content. Passing only an opaque id left the model classifying an identifier
(confirmed ungrounded on real onboarded data), so facts are non-optional.
"""
import logging
from typing import Any, Dict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.sales.agents.gated_runner import run_gated_sales_skill
from app.sales.models.leads import Lead
from app.services.json_utils import plain_facts

logger = logging.getLogger(__name__)


class LeadScoringAgent:
    async def score_lead(self, db: AsyncSession, lead_id: str, tenant_id: str) -> Dict[str, Any]:
        logger.info(f"LeadScoringAgent scoring lead {lead_id}")
        lead = (await db.execute(
            select(Lead).where(Lead.id == lead_id, Lead.tenant_id == tenant_id)
        )).scalar_one_or_none()
        if not lead:
            raise ValueError(f"Lead {lead_id} not found")

        facts = {
            "company": lead.company,
            "contact_name": lead.contact_name,
            "source": lead.source,
            "is_converted": lead.is_converted,
        }
        facts = plain_facts(facts)
        steps = [
            {"step": 1, "name": "Score ICP",
             "prompt": f"Score this lead against the ideal customer profile: {facts}"},
            {"step": 2, "name": "Intent Signals",
             "prompt": "Assess intent signals from the lead source and profile."},
        ]
        return await run_gated_sales_skill(
            skill_id="sales_lead_scoring",
            steps=steps,
            context={
                "lead_id": lead_id, "tenant_id": tenant_id, **facts,
                "instruction": "Output strict JSON: {icp_score, intent_level, recommended_action}.",
            },
            tenant_id=tenant_id,
        )
