"""
KAEOS Enterprise Governance Engine
Phase 15: Governance Engine
Dynamic Attribute-Based Access Control (ABAC) and Approval Chains.
Evaluates if an agent or user is permitted to execute an action based on context,
state, and compliance policies.
"""

import logging
from typing import Dict, Any

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class GovernanceEngine:
    
    @staticmethod
    async def evaluate_action(db: AsyncSession, tenant_id: str, action: str, actor: str, context: dict) -> Dict[str, Any]:
        """
        Evaluates whether an action is permitted under ABAC rules.
        """
        logger.info(f"GovernanceEngine: Evaluating action {action} by {actor}")
        
        # 1. Base ABAC Policies (e.g. Finance agents cannot write to HR repos)
        is_permitted = await GovernanceEngine._check_abac_policies(action, actor, context)
        
        if not is_permitted:
            return {"permitted": False, "reason": "ABAC Policy Violation", "requires_approval": False}
            
        # 2. Check Approval Chains (e.g. Transactions > $10K require manager)
        approval_req = await GovernanceEngine._check_approval_chain(action, context)
        
        if approval_req["required"]:
            return {
                "permitted": False, 
                "reason": "Approval Required", 
                "requires_approval": True,
                "chain": approval_req["chain"]
            }
            
        return {"permitted": True, "reason": "All checks passed"}

    @staticmethod
    async def _check_abac_policies(action: str, actor: str, context: dict) -> bool:
        """
        Mock ABAC Check.
        """
        # E.g., if actor is "HR Agent" but action is "Update Budget" -> False
        return True

    @staticmethod
    async def _check_approval_chain(action: str, context: dict) -> Dict[str, Any]:
        """
        Determines if an action triggers a multi-step approval chain.
        """
        if action == "execute_payment" and context.get("amount", 0) > 10000:
            return {
                "required": True,
                "chain": ["finance_manager", "cfo"]
            }
        return {"required": False, "chain": []}

    @staticmethod
    async def log_audit_trail(db: AsyncSession, tenant_id: str, action: str, actor: str, context: dict, result: str):
        """
        Logs every decision made by the system for compliance (SOC2/SOX).
        """
        logger.info(f"AUDIT: [{result}] {actor} executed {action} with context {context}")
        # In full implementation, write to SecurityAuditLog table.
