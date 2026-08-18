"""
KAEOS HR Vertical — Gated Skill Runner.

Thin department binding over :mod:`app.agents.department_gate`. HR's policy
(EEOC + GDPR defaults, and ``[]`` honoured as a deliberate "no tags") lives in
``department_gate.HR``.

HR additionally sets ``requires_fairness_assessment`` so HCM-touching decisions
are scored for bias by the fairness gate.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.agents.department_gate import HR, extract_decision

__all__ = ["DEFAULT_HR_COMPLIANCE", "run_gated_hr_skill", "extract_decision"]

DEFAULT_HR_COMPLIANCE = list(HR.default_compliance)


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

    ``compliance_tags=[]`` means "no compliance tags" and is honoured as such
    (the fairness sweep relies on it, because its EEOC check *is* the fairness
    gate); ``None`` falls back to ``DEFAULT_HR_COMPLIANCE``.
    """
    return await HR.run(
        skill_id, steps, context, tenant_id,
        compliance_tags=compliance_tags, confidence=confidence, domain=domain,
        extra_context={"requires_fairness_assessment": requires_fairness},
    )
