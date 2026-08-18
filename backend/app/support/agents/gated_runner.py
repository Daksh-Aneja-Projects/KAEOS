"""
KAEOS Support Vertical — Gated Skill Runner.

Thin department binding over :mod:`app.agents.department_gate`. Support's policy
(GDPR/CCPA/SLA_BREACH/PII_REDACTION defaults, ``support_auto_resolve`` forced to
HITL, and the Gate-6 lawful-basis flag derived from a real ``legal_basis``) lives
in ``department_gate.SUPPORT``.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.agents.department_gate import SUPPORT, extract_decision

__all__ = ["DEFAULT_SUPPORT_COMPLIANCE", "run_gated_support_skill", "extract_decision"]

DEFAULT_SUPPORT_COMPLIANCE = list(SUPPORT.default_compliance)


async def run_gated_support_skill(
    skill_id: str,
    steps: List[Dict[str, Any]],
    context: Dict[str, Any],
    tenant_id: str,
    *,
    compliance_tags: Optional[List[str]] = None,
    confidence: float = 0.85,
    domain: str = "support",
) -> Dict[str, Any]:
    """Run a Support skill through the gated ``AgentExecutor`` and return its result."""
    return await SUPPORT.run(
        skill_id, steps, context, tenant_id,
        compliance_tags=compliance_tags, confidence=confidence, domain=domain,
    )


if __name__ == "__main__":
    # Security-path self-check for the compliance wiring this runner owns:
    # (1) the default tags name checkers that actually exist - the SLA->SLA_BREACH
    #     fix (the old "SLA" resolved to NO checker, so the SLA control was dead);
    # (2) PII_REDACTION on a ticket_text carrying a raw PAN blocks fail-closed -
    #     the CRIT this file re-wires. The customer-content agents route inbound
    #     text under recognized keys (ticket_text/content) so this actually fires.
    from app.compliance.registry import get as _get, run_checks as _run
    assert "SLA" not in DEFAULT_SUPPORT_COMPLIANCE, "unbacked 'SLA' tag regressed"
    for _t in ("SLA_BREACH", "PII_REDACTION"):
        assert _t in DEFAULT_SUPPORT_COMPLIANCE and _get(_t) is not None, _t
    _pan = _run(["PII_REDACTION"], {"ticket_text": "please refund my card 4111 1111 1111 1111"})
    assert not _pan["verified"] and _pan["blocking"], "PAN in ticket_text must block"
    _clean = _run(["PII_REDACTION"], {"ticket_text": "my order never arrived"})
    assert _clean["verified"], "clean ticket_text must pass"
    print("support gated_runner compliance wiring self-check passed")
