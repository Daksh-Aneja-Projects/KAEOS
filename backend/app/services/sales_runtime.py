import logging
import uuid
from typing import Dict, Any, List
from app.services.department_runtime_base import DepartmentRuntimeBase

logger = logging.getLogger(__name__)

class SalesRuntimeService(DepartmentRuntimeBase):
    OBSERVED_EVENTS = ["MAJOR_DEAL_CLOSED", "PIPELINE_DROP", "COMPETITOR_ANNOUNCEMENT"]
    
    AVAILABLE_ACTIONS = [
        {
            "action": "CREATE_DISCOUNT_CAMPAIGN",
            "cost": 50000,
            "risk": 60,
            "time": 7,
            "stability": 70,
            "capability": 80,
            "reversibility": 40,
            "dependency": 10,
            "confidence": 75,
            "mutations": [{"type": "CREATE", "node_label": "DiscountCampaign"}]
        },
        {
            "action": "REASSIGN_TERRITORY",
            "cost": 5000,
            "risk": 80,
            "time": 14,
            "stability": 40,
            "capability": 60,
            "reversibility": 20,
            "dependency": 10,
            "confidence": 60,
            "mutations": [{"type": "CREATE", "node_label": "TerritoryAssignment"}]
        }
    ]
    
    RBAC_MATRIX = {
        "CREATE_DISCOUNT_CAMPAIGN": ["VP_Sales", "SalesDirector"],
        "REASSIGN_TERRITORY": ["VP_Sales"]
    }
    
    GRAPH_SCHEMA = ["DiscountCampaign", "TerritoryAssignment", "Deal", "Pipeline"]

    def get_rbac_matrix(self) -> Dict[str, List[str]]:
        return self.RBAC_MATRIX

    def get_action_limits(self) -> Dict[str, float]:
        return {"CREATE_DISCOUNT_CAMPAIGN": 500000}

    async def _execute_domain_logic(self, action: str, context: Dict[str, Any], timestamp: str, decision_id: str, prov_id: str) -> Dict[str, Any]:
        action_def = next((a for a in self.AVAILABLE_ACTIONS if a["action"] == action), None)
        if not action_def: return {"result": "FAILED", "reason": "Unknown Action"}
            
        target_id = context.get("target_id", f"gen_{uuid.uuid4().hex[:8]}")
        for mutation in action_def.get("mutations", []):
            if mutation["type"] == "CREATE":
                await self.provider.create_node(mutation["node_label"], {"id": f"{mutation['node_label']}_{uuid.uuid4().hex[:8]}", "created_at": timestamp})
                
        return {"result": "SUCCESS", "target_id": target_id}
