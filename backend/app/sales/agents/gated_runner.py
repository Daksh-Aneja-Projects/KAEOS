"""
KAEOS Sales Vertical — Gated Skill Runner

Shared helper that routes a Sales agent action through the full 7-gate pipeline.
Note: Proposal generation always routes to HITL (confidence hardcoded low) for human review.

Gate 6 audit flags are DERIVED from context, not pre-set: a hardcoded
``data_processing_basis_logged=True`` with no real ``legal_basis`` used to make
Gate 6 pass on an assertion instead of a fact, which is not what the flag means.
Mirrors app/hr/agents/gated_runner.py.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, List, Optional

from app.agents.runtime import AgentExecutor
from app.services.compliance import ComplianceEngine
from app.services.hitl_manager import hitl_manager
from app.models.domain import Skill

logger = logging.getLogger(__name__)

# Sales analytics (lead scoring, account health, coaching) process customer
# data -> GDPR, not SOX. SOX's hard human-approver blocker is for financial
# controls; tagging it here blocked every sales agent unconditionally.
# Money-touching skills pass SOX explicitly via compliance_tags.
DEFAULT_SALES_COMPLIANCE = ["GDPR"]


async def run_gated_sales_skill(
    skill_id: str,
    steps: List[Dict[str, Any]],
    context: Dict[str, Any],
    tenant_id: str,
    *,
    compliance_tags: Optional[List[str]] = None,
    confidence: float = 0.85,
    domain: str = "sales",
) -> Dict[str, Any]:
    """Run a Sales skill through the gated ``AgentExecutor`` and return its result."""
    compliance_tags = compliance_tags or list(DEFAULT_SALES_COMPLIANCE)
    execution_id = context.get("execution_id") or str(uuid.uuid4())

    # Proposal generation always requires HITL (customer-facing content)
    if skill_id == "sales_proposal_gen":
        confidence = 0.50  # Force HITL for all proposals

    skill_dict = {
        "skill_id": skill_id,
        "department": domain,
        "steps": steps,
        "compliance_tags": compliance_tags,
        "confidence": confidence,
    }

    skill_obj = Skill(
        skill_id=skill_id,
        department=domain,
        domain=domain,
        compliance_tags=compliance_tags,
        confidence=confidence,
        confidence_tier="INFERRED",
        execution_count=0,
        success_rate=0.0,
        steps=steps,
    )

    ctx = {
        **context,
        "tenant_id": tenant_id,
        "execution_id": execution_id,
        "_skill_obj": skill_obj,
    }
    # Gate 6 audit flags: derive from context, not unconditionally pre-set.
    # A hardcoded True let every GDPR-tagged sales agent pass the audit gate
    # regardless of whether a real lawful basis was ever supplied.
    if any(t in compliance_tags for t in ("GDPR", "HIPAA", "CCPA")):
        ctx.setdefault("data_processing_basis_logged", bool(context.get("legal_basis")))
    if "SOX" in compliance_tags:
        ctx.setdefault("financial_amount_logged", bool(context.get("amount")))

    executor = AgentExecutor(ComplianceEngine(), hitl_manager)
    return await executor.execute_skill(skill_dict, ctx)


def extract_decision(result: Dict[str, Any]) -> Dict[str, Any]:
    """Best-effort parse of the primary step's JSON decision from a gated result."""
    from app.services.json_utils import extract_json_object

    chain = result.get("reasoning_chain") or []
    if not chain:
        return {}
    decision_text = chain[-1].get("decision", "") or ""
    try:
        return extract_json_object(decision_text)
    except ValueError as e:
        logger.warning(f"extract_decision: could not parse JSON decision: {e}")
        return {}
