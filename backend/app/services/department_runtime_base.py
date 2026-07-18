import logging
import uuid
from datetime import datetime
from typing import Dict, Any, List

from app.services.graph.graph_service import GraphService

logger = logging.getLogger(__name__)

class DepartmentRuntimeBase:
    """
    Generic Department Runtime Framework.
    Extracts 85% of operational boilerplate: Provenance, Gating, RBAC, Graph Mutating.
    Subclasses only provide domain constraints and domain-specific node creation.
    """
    
    def __init__(self, graph_service: GraphService):
        self.graph_service = graph_service
        self.provider = graph_service.provider

    async def get_node_count(self, label: str) -> int:
        return sum(1 for n in self.provider.nodes.values() if n.get("type", "") == label or n.get("label") == label)

    def get_rbac_matrix(self) -> Dict[str, List[str]]:
        """Override in subclass. Returns mapping of Action -> Allowed Roles."""
        return {}
        
    def get_action_limits(self) -> Dict[str, float]:
        """Override in subclass. Returns financial/quantitative limits for actions."""
        return {}

    async def _check_rbac(self, action: str, role: str) -> bool:
        rbac_matrix = self.get_rbac_matrix()
        allowed_roles = rbac_matrix.get(action, [])
        return role in allowed_roles

    async def _execute_domain_logic(self, action: str, context: Dict[str, Any], timestamp: str, decision_id: str, prov_id: str) -> Dict[str, Any]:
        """Override in subclass. Handles domain-specific graph mutations."""
        raise NotImplementedError("Domain logic must be implemented by subclass.")

    async def execute_action(self, action: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Global shared execution wrapper.
        Enforces governance, logs provenance, and triggers subclass domain logic.
        """
        logger.info(f"DepartmentRuntime: Executing action: {action}")
        timestamp = datetime.utcnow().isoformat()
        decision_id = context.get("decision_id", f"dec_{uuid.uuid4().hex[:8]}")
        actor_role = context.get("actor_role", "Executive")
        approval_status = context.get("approval_status", "APPROVED")
        
        # 1. Global Governance & Approval Gate
        if approval_status != "APPROVED":
            return {"result": "REJECTED", "reason": f"Decision was {approval_status}", "action_executed": action}
            
        # 2. Global RBAC Enforcement
        if not await self._check_rbac(action, actor_role):
            return {"result": "FAILED", "reason": f"Unauthorized. Role '{actor_role}' cannot perform {action}", "action_executed": action}
            
        # 3. Global Limits Enforcement
        limits = self.get_action_limits()
        if action in limits:
            requested_amount = context.get("amount", 0)
            if requested_amount > limits[action]:
                return {"result": "FAILED", "reason": f"Limit Exceeded. Requested {requested_amount}, Limit {limits[action]}", "action_executed": action}

        prov_id = f"prov_{uuid.uuid4().hex[:8]}"

        # 4. Domain Logic Execution (Handled by Subclass)
        result = await self._execute_domain_logic(action, context, timestamp, decision_id, prov_id)
        
        if result.get("result") == "SUCCESS":
            # 5. Global Provenance Generation
            await self.provider.create_node("ProvenanceRecord", {
                "id": prov_id, 
                "type": f"{action}_EXECUTED", 
                "target_id": result.get("target_id", "unknown"), 
                "decision_id": decision_id, 
                "timestamp": timestamp
            })
            result["provenance_id"] = prov_id
            result["twin_mutated"] = True
            
        return result
