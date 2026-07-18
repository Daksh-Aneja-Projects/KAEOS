import logging
import uuid
from typing import Dict, Any, List
from app.services.department_runtime_base import DepartmentRuntimeBase

logger = logging.getLogger(__name__)

class ITRuntimeService(DepartmentRuntimeBase):
    OBSERVED_EVENTS = ["SYSTEM_OUTAGE", "SECURITY_BREACH", "SERVER_DEGRADATION"]
    
    AVAILABLE_ACTIONS = [
        {
            "action": "FAILOVER_SYSTEM",
            "cost": 10000,
            "risk": 50,
            "time": 1,
            "stability": 60,
            "capability": 90,
            "reversibility": 80,
            "dependency": 40,
            "confidence": 85,
            "mutations": [{"type": "CREATE", "node_label": "FailoverExecution"}]
        },
        {
            "action": "LOCKDOWN_NETWORK",
            "cost": 50000,
            "risk": 90,
            "time": 1,
            "stability": 10,
            "capability": 10,
            "reversibility": 50,
            "dependency": 10,
            "confidence": 95,
            "mutations": [{"type": "CREATE", "node_label": "NetworkLockdown"}]
        }
    ]
    
    RBAC_MATRIX = {
        "FAILOVER_SYSTEM": ["SRE", "ITDirector"],
        "LOCKDOWN_NETWORK": ["CISO", "ITDirector"]
    }
    
    GRAPH_SCHEMA = ["FailoverExecution", "NetworkLockdown", "Server", "Database"]

    def get_rbac_matrix(self) -> Dict[str, List[str]]:
        return self.RBAC_MATRIX

    def get_action_limits(self) -> Dict[str, float]:
        return {"FAILOVER_SYSTEM": 500000}

    async def _execute_domain_logic(self, action: str, context: Dict[str, Any], timestamp: str, decision_id: str, prov_id: str) -> Dict[str, Any]:
        action_def = next((a for a in self.AVAILABLE_ACTIONS if a["action"] == action), None)
        if not action_def: return {"result": "FAILED", "reason": "Unknown Action"}
            
        target_id = context.get("target_id", f"gen_{uuid.uuid4().hex[:8]}")
        for mutation in action_def.get("mutations", []):
            if mutation["type"] == "CREATE":
                await self.provider.create_node(mutation["node_label"], {"id": f"{mutation['node_label']}_{uuid.uuid4().hex[:8]}", "created_at": timestamp})
                
        return {"result": "SUCCESS", "target_id": target_id}
