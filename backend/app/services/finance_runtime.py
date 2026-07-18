import logging
import uuid
from typing import Dict, Any, List
from app.services.department_runtime_base import DepartmentRuntimeBase

logger = logging.getLogger(__name__)

class FinanceRuntimeService(DepartmentRuntimeBase):
    OBSERVED_EVENTS = ["BUDGET_EXCEEDED", "REVENUE_DROP", "FUNDING_REQUESTED"]
    
    AVAILABLE_ACTIONS = [
        {
            "action": "ALLOCATE_FUNDS",
            "cost": 0,
            "risk": 40,
            "time": 2,
            "stability": 90,
            "capability": 50,
            "reversibility": 90,
            "dependency": 10,
            "confidence": 95,
            "mutations": [{"type": "CREATE", "node_label": "BudgetAllocation"}]
        },
        {
            "action": "FREEZE_BUDGET",
            "cost": 0,
            "risk": 80,
            "time": 1,
            "stability": 20,
            "capability": 20,
            "reversibility": 70,
            "dependency": 5,
            "confidence": 90,
            "mutations": [{"type": "CREATE", "node_label": "BudgetFreeze"}]
        }
    ]
    
    RBAC_MATRIX = {
        "ALLOCATE_FUNDS": ["FinanceManager", "CFO"],
        "FREEZE_BUDGET": ["CFO"]
    }
    
    GRAPH_SCHEMA = ["BudgetAllocation", "BudgetFreeze", "CostCenter", "RevenueStream"]

    def get_rbac_matrix(self) -> Dict[str, List[str]]:
        return self.RBAC_MATRIX

    def get_action_limits(self) -> Dict[str, float]:
        return {"ALLOCATE_FUNDS": 5000000}

    async def _execute_domain_logic(self, action: str, context: Dict[str, Any], timestamp: str, decision_id: str, prov_id: str) -> Dict[str, Any]:
        action_def = next((a for a in self.AVAILABLE_ACTIONS if a["action"] == action), None)
        if not action_def: return {"result": "FAILED", "reason": "Unknown Action"}
            
        target_id = context.get("target_id", f"gen_{uuid.uuid4().hex[:8]}")
        for mutation in action_def.get("mutations", []):
            if mutation["type"] == "CREATE":
                await self.provider.create_node(mutation["node_label"], {"id": f"{mutation['node_label']}_{uuid.uuid4().hex[:8]}", "created_at": timestamp})
                
        return {"result": "SUCCESS", "target_id": target_id}
