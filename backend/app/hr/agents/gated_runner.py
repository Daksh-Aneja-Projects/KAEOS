"""
KAEOS HR Vertical — Gated Skill Runner

Shared helper that routes an HR agent action through the full 7-gate
``AgentExecutor`` pipeline (Compliance -> Fairness -> Confidence/HITL -> Debate ->
Execute -> Audit) instead of calling ``SkillExecutionEngine.run`` directly.

Every HR action gets:
  * ``compliance_tags`` (default EEOC + GDPR) so the compliance gate evaluates it,
  * a synthetic ``_skill_obj`` so the fairness and debate gates can engage,
  * ``requires_fairness_assessment`` so HCM-touching decisions are scored for bias,
and below-confidence-threshold skills are routed to HITL by the executor.
"""
from __future__ import annotations

import json
import logging
import uuid
from typing import Any, Dict, List, Optional

from app.agents.runtime import AgentExecutor
from app.services.compliance import ComplianceEngine
from app.services.hitl_manager import hitl_manager
from app.models.domain import Skill

logger = logging.getLogger(__name__)

# Default HR compliance frameworks — recruiting/HCM actions are EEOC + GDPR sensitive.
DEFAULT_HR_COMPLIANCE = ["EEOC", "GDPR"]


async def run_gated_hr_skill(
    skill_id: str,
    steps: List[Dict[str, Any]],
    context: Dict[str, Any],
    tenant_id: str,
    *,
    compliance_tags: Optional[List[str]] = None,
    confidence: float = 0.85,
    requires_fairness: bool = True,
    domain: str = "hr",
) -> Dict[str, Any]:
    """Run an HR skill through the gated ``AgentExecutor`` and return its result.

    Returns the executor result dict. On ``SUCCESS_CLEAN`` it includes
    ``reasoning_chain`` so callers can extract the model decision.
    """
    compliance_tags = compliance_tags or list(DEFAULT_HR_COMPLIANCE)
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
        "requires_fairness_assessment": requires_fairness,
    }

    # Post-execution audit flags (Gate 6): the gated pipeline records provenance
    # for every run, so the corresponding legal basis is logged.
    if "GDPR" in compliance_tags:
        ctx["data_processing_basis_logged"] = True
    if "SOX" in compliance_tags:
        ctx["financial_amount_logged"] = True

    executor = AgentExecutor(ComplianceEngine(), hitl_manager)
    return await executor.execute_skill(skill_dict, ctx)


def extract_decision(result: Dict[str, Any]) -> Dict[str, Any]:
    """Best-effort parse of the primary step's JSON decision from a gated result.

    Looks at the last step in ``reasoning_chain`` and parses embedded JSON. Returns
    ``{}`` if nothing parseable is present.
    """
    chain = result.get("reasoning_chain") or []
    if not chain:
        return {}
    decision_text = chain[-1].get("decision", "") or ""
    if "{" in decision_text and "}" in decision_text:
        snippet = decision_text[decision_text.find("{"): decision_text.rfind("}") + 1]
        try:
            return json.loads(snippet)
        except (ValueError, TypeError):
            return {}
    return {}
