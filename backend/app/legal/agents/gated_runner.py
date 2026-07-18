"""
KAEOS Legal Vertical — Gated Skill Runner

Shared helper that routes a Legal agent action through the full 7-gate
``AgentExecutor`` pipeline with GDPR/CCPA/Privacy compliance enforcement.
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

# Legal compliance: GDPR, CCPA, Privacy, Contract enforcement
DEFAULT_LEGAL_COMPLIANCE = ["GDPR", "CCPA", "PRIVACY"]


async def run_gated_legal_skill(
    skill_id: str,
    steps: List[Dict[str, Any]],
    context: Dict[str, Any],
    tenant_id: str,
    *,
    compliance_tags: Optional[List[str]] = None,
    confidence: float = 0.85,
    domain: str = "legal",
) -> Dict[str, Any]:
    """Run a Legal skill through the gated ``AgentExecutor`` and return its result."""
    compliance_tags = compliance_tags or list(DEFAULT_LEGAL_COMPLIANCE)
    execution_id = context.get("execution_id") or str(uuid.uuid4())

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

    if "GDPR" in compliance_tags or "CCPA" in compliance_tags:
        ctx["data_processing_basis_logged"] = True

    executor = AgentExecutor(ComplianceEngine(), hitl_manager)
    return await executor.execute_skill(skill_dict, ctx)


def extract_decision(result: Dict[str, Any]) -> Dict[str, Any]:
    """Best-effort parse of the primary step's JSON decision from a gated result."""
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
