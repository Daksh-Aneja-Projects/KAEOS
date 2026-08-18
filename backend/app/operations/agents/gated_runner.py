"""
KAEOS Operations Vertical — Gated Skill Runner.

Thin department binding over :mod:`app.agents.department_gate`. Operations'
policy (SOC2 + internal-control tags) lives in ``department_gate.OPERATIONS``.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.agents.department_gate import OPERATIONS, extract_decision

__all__ = ["DEFAULT_OPERATIONS_COMPLIANCE", "run_gated_operations_skill", "extract_decision"]

DEFAULT_OPERATIONS_COMPLIANCE = list(OPERATIONS.default_compliance)


async def run_gated_operations_skill(
    skill_id: str,
    steps: List[Dict[str, Any]],
    context: Dict[str, Any],
    tenant_id: str,
    *,
    compliance_tags: Optional[List[str]] = None,
    confidence: float = 0.85,
    domain: str = "operations",
) -> Dict[str, Any]:
    """Run an Operations skill through the gated ``AgentExecutor``."""
    return await OPERATIONS.run(
        skill_id, steps, context, tenant_id,
        compliance_tags=compliance_tags, confidence=confidence, domain=domain,
    )
