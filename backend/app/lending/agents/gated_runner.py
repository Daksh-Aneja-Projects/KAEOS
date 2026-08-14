"""
KAEOS Lending Vertical - Gated Skill Runner

Routes a Lending agent action through the full 7-gate ``AgentExecutor`` pipeline
(Compliance -> Fairness -> Confidence/HITL -> Debate -> Execute -> Audit) instead
of calling the skill engine directly. Mirrors app/finance/agents/gated_runner.py.

Every Lending action carries ECOA + FAIR_LENDING + TILA compliance tags and a
0.9 confidence floor, so below-threshold decisions route to HITL - the vertical
requires human approval by policy.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, List, Optional

from app.agents.runtime import AgentExecutor
from app.models.domain import Skill
from app.services.compliance import ComplianceEngine
from app.services.hitl_manager import hitl_manager

logger = logging.getLogger(__name__)

DEFAULT_LENDING_COMPLIANCE = ["ECOA", "FAIR_LENDING", "TILA"]
LENDING_CONFIDENCE_FLOOR = 0.9


async def run_gated_lending_skill(
    skill_id: str,
    steps: List[Dict[str, Any]],
    context: Dict[str, Any],
    tenant_id: str,
    *,
    compliance_tags: Optional[List[str]] = None,
    confidence: float = LENDING_CONFIDENCE_FLOOR,
    domain: str = "lending",
) -> Dict[str, Any]:
    """Run a Lending skill through the gated ``AgentExecutor`` and return its result."""
    compliance_tags = compliance_tags or list(DEFAULT_LENDING_COMPLIANCE)
    execution_id = context.get("execution_id") or str(uuid.uuid4())

    skill_dict = {
        "skill_id": skill_id,
        "department": domain,
        "steps": steps,
        "compliance_tags": compliance_tags,
        "confidence": confidence,
    }

    # Synthetic (non-persisted) Skill so the fairness + debate gates can engage.
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
        "has_human_approver": context.get("has_human_approver", False),
    }

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
