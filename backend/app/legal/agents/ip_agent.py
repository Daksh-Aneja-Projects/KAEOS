"""
KAEOS Legal Domain — IP Agent

Context-grounding: the agent loads the real entity and reasons over its
content, matching the other four legal agents (contract_review_agent.py,
compliance_audit_agent.py, litigation_agent.py, privacy_dsar_agent.py).

Governance: abandoning or activating a patent is an irreversible business
decision, so it MUST route through the same 7-gate AgentExecutor pipeline
(compliance -> fairness -> confidence/HITL -> debate -> execute -> audit) as
every other legal agent — never a bare LLMRouter call.
"""
import logging
from typing import Any, Dict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.legal.agents.gated_runner import run_gated_legal_skill, extract_decision
from app.legal.models.ip import IPStatus, Patent
from app.services.json_utils import plain_facts

logger = logging.getLogger(__name__)


class IPAgent:
    """Agent for evaluating patentability of corporate IP filings."""

    async def evaluate_patentability(self, db: AsyncSession, patent_id: str, tenant_id: str) -> Dict[str, Any]:
        """Evaluates whether a patent abstract meets the non-obviousness criteria for USPTO filing."""
        patent = (await db.execute(
            select(Patent).where(Patent.id == patent_id, Patent.tenant_id == tenant_id)
        )).scalar_one_or_none()
        if not patent:
            raise ValueError(f"Patent registration {patent_id} not found")

        logger.info(f"IPAgent analyzing patentability of: {patent.title}")

        facts = {
            "title": patent.title,
            "inventors": patent.inventors,
            "abstract": (patent.abstract or "")[:1500],
            "jurisdiction": patent.jurisdiction,
            "status": patent.status.value if hasattr(patent.status, "value") else patent.status,
        }
        facts = plain_facts(facts)
        steps = [
            {"step": 1, "name": "Prior Art Search",
             "prompt": f"Evaluate this patent application abstract for patentability: {facts}"},
            {"step": 2, "name": "Novelty Determination",
             "prompt": "Determine non-obviousness and novelty against standard prior-art databases."},
        ]
        result = await run_gated_legal_skill(
            skill_id="legal_ip_patentability",
            steps=steps,
            context={
                "patent_id": patent_id, "tenant_id": tenant_id, **facts,
                "instruction": (
                    "Output strict JSON: {is_novel, confidence_score, "
                    "prior_art_found, recommendation}."
                ),
            },
            tenant_id=tenant_id,
            confidence=0.75,  # An irreversible status change needs human review
        )
        if result.get("status") == "PENDING_HITL":
            return {"status": "PENDING_HITL", "patent_id": patent_id, "execution_id": result.get("execution_id")}
        if result.get("status") == "SUCCESS_CLEAN":
            decision = extract_decision(result)

            # Abandoning a patent is irreversible, so it must require an explicit
            # negative — never the mere ABSENCE of a positive signal. A response
            # that omits `is_novel` (or is uncertain) leaves the patent under
            # review rather than silently killing a potentially novel filing.
            novel = decision.get("is_novel")
            if novel is True:
                patent.status = IPStatus.ACTIVE
            elif novel is False:
                patent.status = IPStatus.ABANDONED
            # else: unknown — leave status unchanged, keep under review.

            db.add(patent)
            await db.commit()

            return {
                "status": "success",
                "patent_id": patent_id,
                "decision": decision,
                "execution_id": result.get("execution_id"),
            }
        return result
