"""
KAEOS Healthcare Vertical — Gated Skill Runner

Routes a Healthcare agent action through the full 7-gate ``AgentExecutor``
pipeline (Compliance -> Fairness -> Confidence/HITL -> Debate -> Execute ->
Audit). Mirrors app/finance/agents/gated_runner.py.

Healthcare-specific posture (matches packs/healthcare.yaml):
  * ``compliance_tags`` default to the HIPAA + Part 2 deterministic checkers, so
    the compliance gate evaluates every disclosure against real statutory rules.
  * ``always_hitl=True`` on the skill so EVERY clinical action routes to a human
    at Gate 3 (requires_hitl in the pack) regardless of confidence.
  * ``confidence`` default 0.95 (the pack's confidence floor) - cosmetic given
    always_hitl, but keeps the synthetic skill honest about the risk appetite.
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

# Default Healthcare compliance frameworks — every clinical action is HIPAA +
# 42 CFR Part 2 sensitive. These tags have real deterministic checkers.
DEFAULT_HEALTHCARE_COMPLIANCE = [
    "HIPAA_MINIMUM_NECESSARY", "HIPAA_AUTHORIZATION", "PART2",
]

CONFIDENCE_FLOOR = 0.95


async def run_gated_healthcare_skill(
    skill_id: str,
    steps: List[Dict[str, Any]],
    context: Dict[str, Any],
    tenant_id: str,
    *,
    compliance_tags: Optional[List[str]] = None,
    confidence: float = CONFIDENCE_FLOOR,
    domain: str = "healthcare",
    requires_hitl: bool = True,
) -> Dict[str, Any]:
    """Run a Healthcare skill through the gated ``AgentExecutor``.

    ``is None`` (not truthiness): an explicit [] means "no compliance tags" and
    must not silently fall back to the HIPAA default.
    """
    if compliance_tags is None:
        compliance_tags = list(DEFAULT_HEALTHCARE_COMPLIANCE)
    execution_id = context.get("execution_id") or str(uuid.uuid4())

    skill_dict = {
        "skill_id": skill_id,
        "department": domain,
        "steps": steps,
        "compliance_tags": compliance_tags,
        "confidence": confidence,
        # Authoritative always-HITL flag: a clinical action can never be
        # de-escalated below a human at Gate 3 (see is_high_consequence).
        "always_hitl": bool(requires_hitl),
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

    # Gate 6 audit flag: HIPAA disclosures must carry a lawful-basis fact, not
    # just an assertion. Derive from context; never unconditionally pre-set.
    ctx.setdefault("data_processing_basis_logged", bool(context.get("legal_basis")))

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
