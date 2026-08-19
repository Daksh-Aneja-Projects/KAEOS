"""KAEOS Legal Domain - Compliance Audit Agent

Context-grounding: the agent loads the real entity and reasons over its
content. Passing only an opaque id left the model classifying an identifier
(confirmed ungrounded on real onboarded data), so facts are non-optional.
"""
import logging
from typing import Any, Dict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.legal.agents.gated_runner import run_gated_legal_skill, extract_decision
from app.legal.models.compliance import ComplianceObligation, ObligationStatus
from app.services.json_utils import enum_value, plain_facts

logger = logging.getLogger(__name__)


class ComplianceAuditAgent:
    """Compliance obligation audit agent."""

    async def audit_obligation(self, db: AsyncSession, obligation_id: str, tenant_id: str) -> Dict[str, Any]:
        logger.info(f"ComplianceAuditAgent auditing obligation {obligation_id}")
        ob = (await db.execute(
            select(ComplianceObligation).where(
                ComplianceObligation.id == obligation_id,
                ComplianceObligation.tenant_id == tenant_id,
            )
        )).scalar_one_or_none()
        if not ob:
            raise ValueError(f"Compliance obligation {obligation_id} not found")

        facts = {
            "title": ob.title,
            "description": (ob.description or "")[:1200],
            "requirement_id": ob.requirement_id,
            "owner": ob.owner,
            "due_date": str(ob.due_date) if ob.due_date else None,
            "status": enum_value(ob.status),
            "has_evidence": bool(ob.evidence_path),
        }
        facts = plain_facts(facts)
        steps = [
            {"step": 1, "name": "Gather Evidence",
             "prompt": f"Review this compliance obligation and its evidence state: {facts}"},
            {"step": 2, "name": "Assess Compliance",
             "prompt": "Assess pass/fail for the obligation based on the facts above."},
        ]
        result = await run_gated_legal_skill(
            skill_id="legal_compliance_audit",
            steps=steps,
            context={
                "obligation_id": obligation_id, "tenant_id": tenant_id, **facts,
                # GDPR Gate-6 lawful basis: auditing a regulatory obligation is
                # processing to comply with a legal obligation (Art.6(1)(c)).
                "legal_basis": "legal_obligation:regulatory_compliance_audit",
                "instruction": "Output strict JSON: {compliant, gaps, remediation, risk_level}.",
            },
            tenant_id=tenant_id,
            compliance_tags=["GDPR", "CCPA"],
        )
        if result.get("status") == "PENDING_HITL":
            return {
                "status": "PENDING_HITL",
                "obligation_id": obligation_id,
                "execution_id": result.get("execution_id"),
            }
        if result.get("status") == "SUCCESS_CLEAN":
            decision = extract_decision(result)

            # Persist the AI's verdict onto the obligation. An explicit `false`
            # is left alone rather than fabricated into a status the model never
            # asserted (ObligationStatus has no NON_COMPLIANT state); only an
            # explicit `true` advances PENDING/OVERDUE to COMPLETED.
            compliant = decision.get("compliant")
            if compliant is True:
                ob.status = ObligationStatus.COMPLETED

            db.add(ob)
            await db.commit()

            return {
                "status": "SUCCESS_CLEAN",
                "obligation_id": obligation_id,
                "decision": decision,
                "execution_id": result.get("execution_id"),
            }
        return result
