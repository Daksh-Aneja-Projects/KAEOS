"""KAEOS Legal Domain - Litigation Agent

Context-grounding: the agent loads the real entity and reasons over its
content. Passing only an opaque id left the model classifying an identifier
(confirmed ungrounded on real onboarded data), so facts are non-optional.
"""
import logging
from typing import Any, Dict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.legal.agents.gated_runner import run_gated_legal_skill, extract_decision
from app.legal.models.litigation import Case
from app.services.json_utils import enum_value, plain_facts

logger = logging.getLogger(__name__)


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
            "stage": enum_value(case.stage),
            "exposure_amount": case.exposure_amount,
            "opposing_party": case.opposing_party,
            "description": (case.description or "")[:1200],
            "outcome": enum_value(case.outcome) if case.outcome else None,
        }
        facts = plain_facts(facts)
        steps = [
            {"step": 1, "name": "Assess Strength",
             "prompt": f"Assess the strength of this litigation case: {facts}"},
            {"step": 2, "name": "Risk Score",
             "prompt": "Produce a risk score and exposure assessment from the case facts."},
        ]
        result = await run_gated_legal_skill(
            skill_id="legal_litigation_eval",
            steps=steps,
            context={
                "case_id": case_id, "tenant_id": tenant_id, **facts,
                # GDPR Gate-6 lawful basis: evaluating a case is processing for
                # the establishment, exercise or defence of legal claims
                # (Art.6(1)(f) legitimate interests; Art.9(2)(f) for any special
                # categories in the record).
                "legal_basis": "legitimate_interests:legal_claim_defense",
                "instruction": "Output strict JSON: {case_strength, risk_score, settle_or_fight, rationale}.",
            },
            tenant_id=tenant_id,
        )
        if result.get("status") == "PENDING_HITL":
            return {"status": "PENDING_HITL", "case_id": case_id, "execution_id": result.get("execution_id")}
        if result.get("status") == "SUCCESS_CLEAN":
            decision = extract_decision(result)

            # Persist the AI's assessment onto the case outcome narrative. Only
            # append fields the model actually returned - never fabricate a
            # verdict for a field it left out.
            parts = []
            if decision.get("case_strength"):
                parts.append(f"Case strength: {decision['case_strength']}.")
            if decision.get("risk_score") is not None:
                parts.append(f"Risk score: {decision['risk_score']}.")
            if decision.get("settle_or_fight"):
                parts.append(f"Recommendation: {decision['settle_or_fight']}.")
            if decision.get("rationale"):
                parts.append(str(decision["rationale"]))
            if parts:
                case.outcome = " ".join(parts)

            db.add(case)
            await db.commit()

            return {
                "status": "success",
                "case_id": case_id,
                "decision": decision,
                "execution_id": result.get("execution_id"),
            }
        return result
