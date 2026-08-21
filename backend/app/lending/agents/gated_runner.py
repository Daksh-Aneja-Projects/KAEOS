"""
KAEOS Lending Vertical — Gated Skill Runner.

Thin department binding over :mod:`app.agents.department_gate`. Lending's policy
(ECOA / fair-lending / TILA tags, 0.9 confidence floor) lives in
``department_gate.LENDING``.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.agents.department_gate import LENDING, extract_decision

__all__ = [
    "DEFAULT_LENDING_COMPLIANCE", "LENDING_CONFIDENCE_FLOOR",
    "run_gated_lending_skill", "extract_decision",
]

DEFAULT_LENDING_COMPLIANCE = list(LENDING.default_compliance)
LENDING_CONFIDENCE_FLOOR = LENDING.default_confidence


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
    """Run a Lending skill through the gated ``AgentExecutor``."""
    return await LENDING.run(
        skill_id, steps, context, tenant_id,
        compliance_tags=compliance_tags, confidence=confidence, domain=domain,
        # Normalised to a definite value so the ECOA/TILA checkers see an
        # explicit "no approver" rather than a missing key.
        # H18: seed the Gate-6 audit sources every lending skill shares — the
        # fair-lending legal_basis (a real regulatory obligation, not asserted)
        # and the loan amount the caller carried. setdefault semantics in the
        # audit flag mean a caller-supplied value always wins.
        extra_context={
            "has_human_approver": context.get("has_human_approver", False),
            "legal_basis": context.get("legal_basis")
            or "regulatory_obligation:ecoa_fair_lending",
            "amount": context.get("amount"),
        },
    )
