"""
KAEOS Finance Vertical — Gated Skill Runner.

Thin department binding over :mod:`app.agents.department_gate`. Finance's policy
(SOX + GAAP + PCI defaults and the Gate-6 amount/PCI audit flags) lives in
``department_gate.FINANCE``.

Finance additionally resolves the SOX four-eyes attribution: ``check_sox``
requires a maker and an approver that are distinct, resolvable identities, and
fails closed otherwise.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.agents.department_gate import FINANCE, extract_decision

__all__ = ["DEFAULT_FINANCE_COMPLIANCE", "run_gated_finance_skill", "extract_decision"]

DEFAULT_FINANCE_COMPLIANCE = list(FINANCE.default_compliance)


async def run_gated_finance_skill(
    skill_id: str,
    steps: List[Dict[str, Any]],
    context: Dict[str, Any],
    tenant_id: str,
    *,
    compliance_tags: Optional[List[str]] = None,
    confidence: float = 0.85,
    domain: str = "finance",
) -> Dict[str, Any]:
    """Run a Finance skill through the gated ``AgentExecutor`` and return its result."""
    from app.core.context import current_actor

    # SOX gate: the approver's identity STRING when a human approved, else
    # False. A bare True is treated as unverifiable four-eyes and fails closed.
    approved = context.get("has_human_approver", False)
    return await FINANCE.run(
        skill_id, steps, context, tenant_id,
        compliance_tags=compliance_tags, confidence=confidence, domain=domain,
        extra_context={
            "has_human_approver": approved,
            # The MAKER is the initiating actor, the APPROVER is the human who
            # approved; check_sox requires them to be distinct identities.
            "maker": context.get("maker") or current_actor.get(),
            "approver": context.get("approver") or (approved if isinstance(approved, str) else None),
        },
    )
