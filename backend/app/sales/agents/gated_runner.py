"""
KAEOS Sales Vertical — Gated Skill Runner.

Thin department binding over :mod:`app.agents.department_gate`. Sales' policy
(GDPR-only defaults, and ``sales_proposal_gen`` forced to HITL) lives in
``department_gate.SALES``.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.agents.department_gate import SALES, extract_decision

__all__ = ["DEFAULT_SALES_COMPLIANCE", "run_gated_sales_skill", "extract_decision"]

DEFAULT_SALES_COMPLIANCE = list(SALES.default_compliance)


async def run_gated_sales_skill(
    skill_id: str,
    steps: List[Dict[str, Any]],
    context: Dict[str, Any],
    tenant_id: str,
    *,
    compliance_tags: Optional[List[str]] = None,
    confidence: float = 0.85,
    domain: str = "sales",
) -> Dict[str, Any]:
    """Run a Sales skill through the gated ``AgentExecutor``."""
    return await SALES.run(
        skill_id, steps, context, tenant_id,
        compliance_tags=compliance_tags, confidence=confidence, domain=domain,
    )
