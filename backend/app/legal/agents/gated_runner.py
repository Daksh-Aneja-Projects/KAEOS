"""
KAEOS Legal Vertical — Gated Skill Runner.

Thin department binding over :mod:`app.agents.department_gate`. Legal's policy
lives in ``department_gate.LEGAL`` — including the ``REVIEW:`` note on its
Gate-6 lawful-basis flag, which is still asserted rather than derived.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.agents.department_gate import LEGAL, extract_decision

__all__ = ["DEFAULT_LEGAL_COMPLIANCE", "run_gated_legal_skill", "extract_decision"]

DEFAULT_LEGAL_COMPLIANCE = list(LEGAL.default_compliance)


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
    """Run a Legal skill through the gated ``AgentExecutor``."""
    return await LEGAL.run(
        skill_id, steps, context, tenant_id,
        compliance_tags=compliance_tags, confidence=confidence, domain=domain,
    )
