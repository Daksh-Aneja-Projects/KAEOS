import logging
import uuid
from typing import Dict, Any, List
from app.services.department_runtime_base import DepartmentRuntimeBase

logger = logging.getLogger(__name__)

class CustomerSuccessRuntimeService(DepartmentRuntimeBase):
    OBSERVED_EVENTS = ["CHURN_RISK_HIGH", "NPS_DROP", "ESCALATION_TICKET"]
    
    AVAILABLE_ACTIONS = [
        {
            "action": "DEPLOY_TIGER_TEAM",
            "cost": 15000,
            "risk": 20,
            "time": 2,
            "stability": 60,
            "capability": 95,
            "reversibility": 80,
            "dependency": 10,
            "confidence": 85,
            "mutations": [{"type": "CREATE", "node_label": "TigerTeamDeployment"}]
        },
        {
            "action": "GRANT_SERVICE_CREDIT",
            "cost": 50000,
            "risk": 10,
            "time": 1,
            "stability": 90,
            "capability": 50,
            "reversibility": 100,
            "dependency": 0,
            "confidence": 90,
            "mutations": [{"type": "CREATE", "node_label": "ServiceCredit"}]
        }
    ]
    
    RBAC_MATRIX = {
        "DEPLOY_TIGER_TEAM": ["CSM", "VP_CS"],
        "GRANT_SERVICE_CREDIT": ["VP_CS", "Director_CS"]
    }
    
    GRAPH_SCHEMA = ["TigerTeamDeployment", "ServiceCredit", "Customer", "Ticket"]

    def get_rbac_matrix(self) -> Dict[str, List[str]]:
        return self.RBAC_MATRIX

    def get_action_limits(self) -> Dict[str, float]:
        return {"GRANT_SERVICE_CREDIT": 100000}

    async def _execute_domain_logic(self, action: str, context: Dict[str, Any], timestamp: str, decision_id: str, prov_id: str) -> Dict[str, Any]:
        action_def = next((a for a in self.AVAILABLE_ACTIONS if a["action"] == action), None)
        if not action_def: return {"result": "FAILED", "reason": "Unknown Action"}
            
        target_id = context.get("target_id", f"gen_{uuid.uuid4().hex[:8]}")
        for mutation in action_def.get("mutations", []):
            if mutation["type"] == "CREATE":
                await self.provider.create_node(mutation["node_label"], {"id": f"{mutation['node_label']}_{uuid.uuid4().hex[:8]}", "created_at": timestamp})
                
        return {"result": "SUCCESS", "target_id": target_id}
