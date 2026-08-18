"""
KAEOS Engineering Vertical — Gated Skill Runner.

Thin department binding over :mod:`app.agents.department_gate`. Engineering's
policy lives in ``department_gate.ENGINEERING``: SOC2 + change-management by
default, and the full change-management control set plus forced human approval
for production deploys.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.agents.department_gate import (
    DEPLOY_COMPLIANCE as _DEPLOY_COMPLIANCE,
    ENGINEERING,
    _ENGINEERING_DEPLOY_SKILL,
    extract_decision,
)

__all__ = [
    "DEFAULT_ENGINEERING_COMPLIANCE", "DEPLOY_COMPLIANCE", "ALWAYS_HITL_SKILLS",
    "run_gated_engineering_skill", "extract_decision",
]

DEFAULT_ENGINEERING_COMPLIANCE = list(ENGINEERING.default_compliance)
DEPLOY_COMPLIANCE = list(_DEPLOY_COMPLIANCE)
# Skills that mutate production always route to a human, regardless of the
# model's confidence.
ALWAYS_HITL_SKILLS = {_ENGINEERING_DEPLOY_SKILL}


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
    return await ENGINEERING.run(
        skill_id, steps, context, tenant_id,
        compliance_tags=compliance_tags, confidence=confidence, domain=domain,
    )
