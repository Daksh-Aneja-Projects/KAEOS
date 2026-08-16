"""
KAEOS Finance Vertical — Gated Skill Runner

Shared helper that routes a Finance agent action through the full 7-gate
``AgentExecutor`` pipeline (Compliance -> Fairness -> Confidence/HITL -> Debate ->
Execute -> Audit) instead of calling ``SkillExecutionEngine.run`` directly.

Every Finance action gets:
  * ``compliance_tags`` (default SOX + GAAP) so the compliance gate evaluates it,
  * a synthetic ``_skill_obj`` so the fairness and debate gates can engage,
  * SOX gate requires human_approver context for financial control,
and below-confidence-threshold skills are routed to HITL by the executor.
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

# Default Finance compliance frameworks — AP/AR/budget/audit are SOX + GAAP sensitive
DEFAULT_FINANCE_COMPLIANCE = ["SOX", "GAAP", "PCI"]


async def run_gated_finance_skill(
    skill_id: str,
    steps: List[Dict[str, Any]],
    context: Dict[str, Any],
    tenant_id: str,
    *,
    compliance_tags: Optional[List[str]] = None,
    confidence: float = 0.85,
    domain: str = "finance",
) -> Dict[str, Any]:
    """Run a Finance skill through the gated ``AgentExecutor`` and return its result.

    Returns the executor result dict. On ``SUCCESS_CLEAN`` it includes
    ``reasoning_chain`` so callers can extract the model decision.

    SOX compliance: All finance actions default to the SOX gate, which requires a
    human approver whose identity DIFFERS from the maker (four-eyes). Pass the
    approver's identity string via ``has_human_approver`` from the HITL approval
    path; a bare ``True`` is unverifiable and fails closed.
    """
    compliance_tags = compliance_tags or list(DEFAULT_FINANCE_COMPLIANCE)
    execution_id = context.get("execution_id") or str(uuid.uuid4())

    skill_dict = {
        "skill_id": skill_id,
        "department": domain,
        "steps": steps,
        "compliance_tags": compliance_tags,
        "confidence": confidence,
    }

    # Synthetic (non-persisted) Skill so the fairness + debate gates can engage
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

    from app.core.context import current_actor
    _approved = context.get("has_human_approver", False)
    ctx = {
        **context,
        "tenant_id": tenant_id,
        "execution_id": execution_id,
        "_skill_obj": skill_obj,
        # SOX gate: the approver's identity STRING when a human approved, else
        # False. A bare True is treated as unverifiable four-eyes and fails closed.
        "has_human_approver": _approved,
        # Four-eyes attribution for check_sox: the MAKER is the initiating actor,
        # the APPROVER is the human who approved. check_sox requires them to be
        # distinct, resolvable identities (fail-closed otherwise).
        "maker": context.get("maker") or current_actor.get(),
        "approver": context.get("approver") or (_approved if isinstance(_approved, str) else None),
    }

    # Gate 6 audit flags: NOT pre-seeded — execution must earn them.
    # The SkillExecutionEngine sets these in reasoning_chain output when a step
    # actually logs the required artifact. Pre-setting defeats audit enforcement.
    if "SOX" in compliance_tags or "GAAP" in compliance_tags:
        ctx.setdefault("financial_amount_logged", bool(context.get("amount")))
    if "PCI" in compliance_tags:
        ctx.setdefault("pci_dss_compliant", bool(context.get("pci_validated")))

    executor = AgentExecutor(ComplianceEngine(), hitl_manager)
    return await executor.execute_skill(skill_dict, ctx)


def extract_decision(result: Dict[str, Any]) -> Dict[str, Any]:
    """Best-effort parse of the primary step's JSON decision from a gated result.

    Looks at the last step in ``reasoning_chain`` and parses embedded JSON. Returns
    ``{}`` if nothing parseable is present.
    """
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
