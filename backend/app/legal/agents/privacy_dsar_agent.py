"""KAEOS Legal Domain - Privacy DSAR Agent

Context-grounding: the agent loads the real entity and reasons over its
content. Passing only an opaque id left the model classifying an identifier
(confirmed ungrounded on real onboarded data), so facts are non-optional.
"""
import logging
from typing import Any, Dict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.legal.agents.gated_runner import run_gated_legal_skill
from app.legal.models.privacy import DataSubjectRequest
from app.services.json_utils import plain_facts

logger = logging.getLogger(__name__)


def _v(x):
    return getattr(x, "value", x)


class PrivacyDSARAgent:
    async def process_dsar(self, db: AsyncSession, dsar_id: str, tenant_id: str) -> Dict[str, Any]:
        logger.info(f"PrivacyDSARAgent processing DSAR {dsar_id}")
        dsar = (await db.execute(
            select(DataSubjectRequest).where(
                DataSubjectRequest.id == dsar_id,
                DataSubjectRequest.tenant_id == tenant_id,
            )
        )).scalar_one_or_none()
        if not dsar:
            raise ValueError(f"DSAR {dsar_id} not found")

        facts = {
            "request_type": _v(dsar.request_type),
            "status": _v(dsar.status),
            "request_date": str(dsar.request_date) if dsar.request_date else None,
            "deadline_date": str(dsar.deadline_date) if dsar.deadline_date else None,
            "assigned_officer": dsar.assigned_officer,
            "prior_validation": dsar.ai_validation,
        }
        facts = plain_facts(facts)
        steps = [
            {"step": 1, "name": "Locate Records",
             "prompt": f"Plan the record location for this data subject request: {facts}"},
            {"step": 2, "name": "Produce Response",
             "prompt": "Generate a GDPR 30-day compliant response plan for the request."},
        ]
        return await run_gated_legal_skill(
            skill_id="legal_privacy_dsar",
            steps=steps,
            context={
                "dsar_id": dsar_id, "tenant_id": tenant_id, **facts,
                "instruction": "Output strict JSON: {response_plan, systems_to_query, deadline_risk}.",
            },
            tenant_id=tenant_id,
            compliance_tags=["GDPR", "CCPA"],
        )
