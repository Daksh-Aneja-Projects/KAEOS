"""
KAEOS Support Vertical — Gated Skill Runner

Shared helper that routes a Support agent action through the full 7-gate pipeline.
Note: Customer-facing responses (auto-resolve) always require HITL to prevent autonomous
customer communication and ensure human oversight.
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

# PII_REDACTION runs the real Luhn/SSN/API-key checker on outbound customer
# content (fail-closed BLOCK). SLA_BREACH is the tag the checker actually
# registers - the old "SLA" resolved to NO checker, so the SLA control never
# ran. Every gated support agent handles customer content, so both belong in
# the shared default. (resolution_agent/kb_agent bypass this runner entirely -
# a separate ungoverned-drafting gap, not fixable here.)
DEFAULT_SUPPORT_COMPLIANCE = ["GDPR", "CCPA", "SLA_BREACH", "PII_REDACTION"]


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
    compliance_tags = compliance_tags or list(DEFAULT_SUPPORT_COMPLIANCE)
    execution_id = context.get("execution_id") or str(uuid.uuid4())

    # Auto-resolve (customer-facing responses) always requires HITL
    if skill_id == "support_auto_resolve":
        confidence = 0.79  # Force HITL for customer responses

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

    # Gate 6 audit flag: derive from context, never hardcode True. A hardcoded
    # flag asserted "lawful basis logged" even when no basis was ever supplied,
    # so every GDPR/CCPA-tagged support run failed Gate 6 (FAILED_AUDIT) because
    # the audit also requires a real legal_basis. Mirrors sales/agents/gated_runner.
    if any(t in compliance_tags for t in ("GDPR", "HIPAA", "CCPA")):
        ctx.setdefault("data_processing_basis_logged", bool(context.get("legal_basis")))

    executor = AgentExecutor(ComplianceEngine(), hitl_manager)
    return await executor.execute_skill(skill_dict, ctx)


def extract_decision(result: Dict[str, Any]) -> Dict[str, Any]:
    """Best-effort parse of the primary step's JSON decision from a gated result."""
    from app.services.json_utils import extract_json_object

    chain = result.get("reasoning_chain") or []
    if not chain:
        return {}
    decision_text = chain[-1].get("decision", "") or ""
    try:
        return extract_json_object(decision_text)
    except ValueError as e:
        logger.warning(f"extract_decision: could not parse JSON decision: {e}")
        return {}


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
