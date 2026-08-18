"""
KAEOS Healthcare Vertical — Gated Skill Runner.

Thin department binding over :mod:`app.agents.department_gate`. Healthcare's
policy lives in ``department_gate.HEALTHCARE`` and matches packs/healthcare.yaml:
HIPAA + Part 2 deterministic checkers, a 0.95 confidence floor, ``[]`` honoured
as a deliberate "no tags", and ``always_hitl`` so every clinical action routes to
a human at Gate 3 regardless of confidence.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.agents.department_gate import HEALTHCARE, extract_decision

__all__ = [
    "DEFAULT_HEALTHCARE_COMPLIANCE", "CONFIDENCE_FLOOR",
    "run_gated_healthcare_skill", "extract_decision",
]

DEFAULT_HEALTHCARE_COMPLIANCE = list(HEALTHCARE.default_compliance)
CONFIDENCE_FLOOR = HEALTHCARE.default_confidence


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
    return await HEALTHCARE.run(
        skill_id, steps, context, tenant_id,
        compliance_tags=compliance_tags, confidence=confidence, domain=domain,
        # Authoritative always-HITL flag: a clinical action can never be
        # de-escalated below a human at Gate 3 (see is_high_consequence).
        extra_skill_fields={"always_hitl": bool(requires_hitl)},
    )
