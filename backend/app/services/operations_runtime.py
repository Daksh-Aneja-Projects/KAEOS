import logging
import uuid
from typing import Dict, Any, List
from app.services.department_runtime_base import DepartmentRuntimeBase

logger = logging.getLogger(__name__)

class OperationsRuntimeService(DepartmentRuntimeBase):
    OBSERVED_EVENTS = ["SUPPLY_CHAIN_DELAY", "CAPACITY_BOTTLENECK", "ASSET_FAILURE"]
    
    AVAILABLE_ACTIONS = [
        {
            "action": "REROUTE_SUPPLY",
            "cost": 25000,
            "risk": 30,
            "time": 7,
            "stability": 70,
            "capability": 80,
            "reversibility": 40,
            "dependency": 50,
            "confidence": 75,
            "mutations": [{"type": "CREATE", "node_label": "SupplyReroute"}]
        },
        {
            "action": "EXPAND_CAPACITY",
            "cost": 200000,
            "risk": 40,
            "time": 90,
            "stability": 85,
            "capability": 100,
            "reversibility": 10,
            "dependency": 60,
            "confidence": 80,
            "mutations": [{"type": "CREATE", "node_label": "CapacityExpansion"}]
        }
    ]
    
    RBAC_MATRIX = {
        "REROUTE_SUPPLY": ["OpsManager", "COO"],
        "EXPAND_CAPACITY": ["COO", "Executive"]
    }
    
    GRAPH_SCHEMA = ["SupplyReroute", "CapacityExpansion", "Warehouse", "LogisticsRoute"]

    def get_rbac_matrix(self) -> Dict[str, List[str]]:
        return self.RBAC_MATRIX

    def get_action_limits(self) -> Dict[str, float]:
        return {"EXPAND_CAPACITY": 10000000}

    async def _execute_domain_logic(self, action: str, context: Dict[str, Any], timestamp: str, decision_id: str, prov_id: str) -> Dict[str, Any]:
        action_def = next((a for a in self.AVAILABLE_ACTIONS if a["action"] == action), None)
        if not action_def: return {"result": "FAILED", "reason": "Unknown Action"}
            
        target_id = context.get("target_id", f"gen_{uuid.uuid4().hex[:8]}")
        for mutation in action_def.get("mutations", []):
            if mutation["type"] == "CREATE":
                await self.provider.create_node(mutation["node_label"], {"id": f"{mutation['node_label']}_{uuid.uuid4().hex[:8]}", "created_at": timestamp})
                
        return {"result": "SUCCESS", "target_id": target_id}
