import logging
import uuid
from typing import Dict, Any, List
from app.services.department_runtime_base import DepartmentRuntimeBase

logger = logging.getLogger(__name__)

class ProcurementRuntimeService(DepartmentRuntimeBase):
    OBSERVED_EVENTS = ["SUPPLIER_RISK_DETECTED", "CONTRACT_EXPIRING", "VENDOR_DEFAULT"]
    
    AVAILABLE_ACTIONS = [
        {
            "action": "CREATE_RFQ",
            "cost": 5000,
            "risk": 10,
            "time": 30,
            "stability": 90,
            "capability": 60,
            "reversibility": 100,
            "dependency": 50,
            "confidence": 85,
            "mutations": [{"type": "CREATE", "node_label": "RFQ"}]
        },
        {
            "action": "TERMINATE_VENDOR",
            "cost": 50000,
            "risk": 90,
            "time": 14,
            "stability": 30,
            "capability": 20,
            "reversibility": 10,
            "dependency": 10,
            "confidence": 60,
            "mutations": [{"type": "CREATE", "node_label": "VendorTermination"}]
        }
    ]
    
    RBAC_MATRIX = {
        "CREATE_RFQ": ["Buyer", "ProcurementManager"],
        "TERMINATE_VENDOR": ["ProcurementManager", "Executive"]
    }
    
    GRAPH_SCHEMA = ["RFQ", "VendorTermination", "Supplier", "Contract"]

    def get_rbac_matrix(self) -> Dict[str, List[str]]:
        return self.RBAC_MATRIX

    def get_action_limits(self) -> Dict[str, float]:
        return {"CREATE_RFQ": 1000000}

    async def _execute_domain_logic(self, action: str, context: Dict[str, Any], timestamp: str, decision_id: str, prov_id: str) -> Dict[str, Any]:
        action_def = next((a for a in self.AVAILABLE_ACTIONS if a["action"] == action), None)
        if not action_def: return {"result": "FAILED", "reason": "Unknown Action"}
            
        target_id = context.get("target_id", f"gen_{uuid.uuid4().hex[:8]}")
        for mutation in action_def.get("mutations", []):
            if mutation["type"] == "CREATE":
                await self.provider.create_node(mutation["node_label"], {"id": f"{mutation['node_label']}_{uuid.uuid4().hex[:8]}", "created_at": timestamp})
                
        return {"result": "SUCCESS", "target_id": target_id}
