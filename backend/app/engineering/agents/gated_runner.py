"""
KAEOS Engineering Vertical — Gated Skill Runner

Routes an Engineering agent action through the full 7-gate pipeline, exactly as
the other five domains do. Production deploys are treated like customer-facing
support responses: they always require human approval, because an autonomous
agent shipping to production is precisely the failure mode enterprises fear.
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

DEFAULT_ENGINEERING_COMPLIANCE = ["SOC2", "CHANGE_MANAGEMENT"]

# Skills that mutate production always route to a human, regardless of the
# model's confidence. Below the 0.82 HITL threshold on purpose.
ALWAYS_HITL_SKILLS = {"engineering_deploy_approval"}


async def run_gated_engineering_skill(
    skill_id: str,
    steps: List[Dict[str, Any]],
    context: Dict[str, Any],
    tenant_id: str,
    *,
    compliance_tags: Optional[List[str]] = None,
    confidence: float = 0.85,
    domain: str = "engineering",
) -> Dict[str, Any]:
    """Run an Engineering skill through the gated ``AgentExecutor``."""
    compliance_tags = compliance_tags or list(DEFAULT_ENGINEERING_COMPLIANCE)
    execution_id = context.get("execution_id") or str(uuid.uuid4())

    if skill_id in ALWAYS_HITL_SKILLS:
        confidence = 0.79  # force human approval for production changes

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

    # SOC2 change management expects an auditable approval trail.
    if "CHANGE_MANAGEMENT" in compliance_tags:
        ctx["change_record_logged"] = True

    executor = AgentExecutor(ComplianceEngine(), hitl_manager)
    return await executor.execute_skill(skill_dict, ctx)


def extract_decision(result: Dict[str, Any]) -> Dict[str, Any]:
    """Best-effort parse of the primary step's JSON decision from a gated result."""
    from app.services.json_utils import extract_json_object

    chain = result.get("reasoning_chain") or []
    if not chain:
        return {}
    try:
        return extract_json_object(chain[-1].get("decision", "") or "")
    except ValueError:
        return {}
