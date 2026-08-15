"""KAEOS Legal Domain - Contract Review Agent

Context-grounding: the agent loads the real entity and reasons over its
content. Passing only an opaque id left the model classifying an identifier
(confirmed ungrounded on real onboarded data), so facts are non-optional.
"""
import logging
from typing import Any, Dict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.legal.agents.gated_runner import run_gated_legal_skill, extract_decision
from app.legal.models.contracts import Contract, ContractClause
from app.services.json_utils import plain_facts

logger = logging.getLogger(__name__)


def _v(x):
    return getattr(x, "value", x)


class ContractReviewAgent:
    """Contract review and risk analysis agent."""

    async def review_contract(self, db: AsyncSession, contract_id: str, tenant_id: str) -> Dict[str, Any]:
        logger.info(f"ContractReviewAgent reviewing contract {contract_id}")
        contract = (await db.execute(
            select(Contract).where(Contract.id == contract_id, Contract.tenant_id == tenant_id)
        )).scalar_one_or_none()
        if not contract:
            raise ValueError(f"Contract {contract_id} not found")

        clause_rows = (await db.execute(
            select(ContractClause).where(
                ContractClause.contract_id == contract_id,
                ContractClause.tenant_id == tenant_id,
            )
        )).scalars().all()
        clause_types = [c.clause_type for c in clause_rows]

        facts = {
            "title": contract.title,
            "counterparty": contract.counterparty,
            "contract_type": _v(contract.contract_type),
            "status": _v(contract.status),
            "contract_value": contract.contract_value,
            "effective_date": str(contract.effective_date) if contract.effective_date else None,
            "expiry_date": str(contract.expiry_date) if contract.expiry_date else None,
            "auto_renew": contract.auto_renew,
            "prior_ai_summary": (contract.ai_summary or "")[:800],
        }
        facts = plain_facts(facts)
        steps = [
            {"step": 1, "name": "Extract Clauses",
             "prompt": f"Extract and categorize the key clauses of this contract: {facts}"},
            {"step": 2, "name": "Identify Risks",
             "prompt": "Identify high-risk clauses (liability, IP assignment, confidentiality, auto-renewal)."},
        ]
        result = await run_gated_legal_skill(
            skill_id="legal_contract_review",
            steps=steps,
            context={
                "contract_id": contract_id, "tenant_id": tenant_id, **facts,
                # CONTRACT_CLAUSE (app/compliance/checkers/legal.py) needs
                # context['contract'] = {type, clauses}. Real clause inventory,
                # not fabricated, so an unmodeled type/no clauses reads ADVISORY.
                "contract": {"type": contract.contract_type, "clauses": clause_types},
                "instruction": "Output strict JSON: {risk_score, high_risk_clauses, recommendation}.",
            },
            tenant_id=tenant_id,
            confidence=0.75,  # Contracts need human review
            compliance_tags=["GDPR", "CCPA", "CONTRACT_CLAUSE"],
        )
        if result.get("status") == "PENDING_HITL":
            return {"status": "PENDING_HITL", "execution_id": result.get("execution_id")}
        if result.get("status") == "SUCCESS_CLEAN":
            decision = extract_decision(result)

            # Persist the AI's conclusion onto the contract — a missing field
            # leaves the prior value alone rather than clobbering it with a
            # fabricated number (honesty contract: never invent a metric).
            risk_score = decision.get("risk_score")
            if risk_score is not None:
                try:
                    contract.ai_risk_score = float(risk_score)
                except (TypeError, ValueError):
                    logger.warning(f"ContractReviewAgent: non-numeric risk_score {risk_score!r}")

            summary_parts = []
            high_risk = decision.get("high_risk_clauses")
            if high_risk:
                clause_list = ", ".join(str(c) for c in high_risk) if isinstance(high_risk, list) else str(high_risk)
                summary_parts.append(f"High-risk clauses: {clause_list}.")
            recommendation = decision.get("recommendation")
            if recommendation:
                summary_parts.append(str(recommendation))
            if summary_parts:
                contract.ai_summary = " ".join(summary_parts)

            db.add(contract)
            await db.commit()

            return {
                "status": "success",
                "contract_id": contract_id,
                "decision": decision,
                "execution_id": result.get("execution_id"),
            }
        return result
