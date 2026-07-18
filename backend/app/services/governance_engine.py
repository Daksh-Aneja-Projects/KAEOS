"""
KAEOS Enterprise Governance Engine
Dynamic Attribute-Based Access Control (ABAC) and Approval Chains.
Evaluates if an agent or user is permitted to execute an action based on context,
state, and compliance policies.
"""

import logging
from typing import Dict, Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import insert

from app.models.domain import SecurityAuditLog

logger = logging.getLogger(__name__)

# Domain boundary rules: which actor prefixes may execute which action prefixes.
# An actor not listed is unrestricted (fail-open for backwards compatibility).
_DOMAIN_BOUNDARIES: dict[str, set[str]] = {
    "hr": {"hr_", "employee_", "recruit_", "onboard_"},
    "finance": {"finance_", "budget_", "invoice_", "payment_", "execute_payment"},
    "legal": {"legal_", "contract_", "compliance_"},
    "sales": {"sales_", "deal_", "pipeline_", "forecast_"},
    "support": {"support_", "ticket_", "escalat"},
    "operations": {"ops_", "process_", "vendor_", "procurement_"},
    "engineering": {"eng_", "deploy_", "incident_", "sprint_"},
}


class GovernanceEngine:

    @staticmethod
    async def evaluate_action(db: AsyncSession, tenant_id: str, action: str, actor: str, context: dict) -> Dict[str, Any]:
        """Evaluates whether an action is permitted under ABAC rules."""
        logger.info(f"GovernanceEngine: Evaluating action {action} by {actor}")

        is_permitted = await GovernanceEngine._check_abac_policies(action, actor, context)

        if not is_permitted:
            await GovernanceEngine.log_audit_trail(db, tenant_id, action, actor, context, "DENIED_ABAC")
            return {"permitted": False, "reason": "ABAC Policy Violation", "requires_approval": False}

        approval_req = await GovernanceEngine._check_approval_chain(action, context)

        if approval_req["required"]:
            await GovernanceEngine.log_audit_trail(db, tenant_id, action, actor, context, "PENDING_APPROVAL")
            return {
                "permitted": False,
                "reason": "Approval Required",
                "requires_approval": True,
                "chain": approval_req["chain"]
            }

        await GovernanceEngine.log_audit_trail(db, tenant_id, action, actor, context, "PERMITTED")
        return {"permitted": True, "reason": "All checks passed"}

    @staticmethod
    async def _check_abac_policies(action: str, actor: str, context: dict) -> bool:
        """
        Attribute-Based Access Control — enforces domain boundary separation.

        An HR agent cannot execute finance actions, a finance agent cannot
        execute HR actions, etc. Actors whose domain is not in the boundary
        table are unrestricted (platform-level, admin, or generic agents).
        """
        actor_lower = actor.lower()
        action_lower = action.lower()

        for domain, allowed_prefixes in _DOMAIN_BOUNDARIES.items():
            actor_is_domain = domain in actor_lower
            if not actor_is_domain:
                continue
            action_in_domain = any(action_lower.startswith(p) for p in allowed_prefixes)
            if action_in_domain:
                return True
            # Actor belongs to this domain but the action doesn't match — check
            # if the action belongs to a DIFFERENT domain (cross-boundary).
            for other_domain, other_prefixes in _DOMAIN_BOUNDARIES.items():
                if other_domain == domain:
                    continue
                if any(action_lower.startswith(p) for p in other_prefixes):
                    logger.warning(
                        f"ABAC DENY: {actor} ({domain}) attempted cross-domain "
                        f"action {action} (belongs to {other_domain})"
                    )
                    return False
            # Action doesn't match any domain boundary — allow (generic action).
            return True

        # Actor not in any domain boundary (platform agent, admin) — unrestricted.
        return True

    @staticmethod
    async def _check_approval_chain(action: str, context: dict) -> Dict[str, Any]:
        """Determines if an action triggers a multi-step approval chain."""
        amount = context.get("amount", 0)
        if action == "execute_payment" and amount > 10000:
            return {"required": True, "chain": ["finance_manager", "cfo"]}
        if action.startswith("contract_") and context.get("contract_value", 0) > 50000:
            return {"required": True, "chain": ["legal_counsel", "cfo"]}
        if action == "employee_termination":
            return {"required": True, "chain": ["hr_director", "legal_counsel"]}
        return {"required": False, "chain": []}

    @staticmethod
    async def log_audit_trail(db: AsyncSession, tenant_id: str, action: str, actor: str, context: dict, result: str):
        """Persist every governance decision to the SecurityAuditLog table."""
        try:
            await db.execute(
                insert(SecurityAuditLog).values(
                    tenant_id=tenant_id,
                    event_type=f"governance:{action}",
                    actor=actor,
                    details={"context": context, "decision": result},
                    severity="INFO" if result == "PERMITTED" else "WARNING",
                )
            )
        except Exception as e:
            logger.error(f"Failed to persist audit trail: {e}")
            # Never let audit persistence failure block the action evaluation.
