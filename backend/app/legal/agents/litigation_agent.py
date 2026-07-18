"""KAEOS Legal Domain - Litigation Agent

Context-grounding: the agent loads the real entity and reasons over its
content. Passing only an opaque id left the model classifying an identifier
(confirmed ungrounded on real onboarded data), so facts are non-optional.
"""
import logging
from typing import Any, Dict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.legal.agents.gated_runner import run_gated_legal_skill
from app.legal.models.litigation import Case
from app.services.json_utils import plain_facts

logger = logging.getLogger(__name__)


def _v(x):
    return getattr(x, "value", x)


class LitigationAgent:
    async def evaluate_case(self, db: AsyncSession, case_id: str, tenant_id: str) -> Dict[str, Any]:
        logger.info(f"LitigationAgent evaluating case {case_id}")
        case = (await db.execute(
            select(Case).where(Case.id == case_id, Case.tenant_id == tenant_id)
        )).scalar_one_or_none()
        if not case:
            raise ValueError(f"Case {case_id} not found")

        facts = {
            "case_name": case.case_name,
            "case_number": case.case_number,
            "court": case.court,
            "stage": _v(case.stage),
            "exposure_amount": case.exposure_amount,
            "opposing_party": case.opposing_party,
            "description": (case.description or "")[:1200],
            "outcome": _v(case.outcome) if case.outcome else None,
        }
        facts = plain_facts(facts)
        steps = [
            {"step": 1, "name": "Assess Strength",
             "prompt": f"Assess the strength of this litigation case: {facts}"},
            {"step": 2, "name": "Risk Score",
             "prompt": "Produce a risk score and exposure assessment from the case facts."},
        ]
        return await run_gated_legal_skill(
            skill_id="legal_litigation_eval",
            steps=steps,
            context={
                "case_id": case_id, "tenant_id": tenant_id, **facts,
                "instruction": "Output strict JSON: {case_strength, risk_score, settle_or_fight, rationale}.",
            },
            tenant_id=tenant_id,
        )
