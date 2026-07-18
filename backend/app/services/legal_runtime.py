import logging
import uuid
from typing import Dict, Any, List
from app.services.department_runtime_base import DepartmentRuntimeBase

logger = logging.getLogger(__name__)

class LegalRuntimeService(DepartmentRuntimeBase):
    OBSERVED_EVENTS = ["LAWSUIT_FILED", "COMPLIANCE_VIOLATION", "CONTRACT_BREACH"]
    
    AVAILABLE_ACTIONS = [
        {
            "action": "INITIATE_LITIGATION_HOLD",
            "cost": 5000,
            "risk": 10,
            "time": 1,
            "stability": 90,
            "capability": 100,
            "reversibility": 100,
            "dependency": 0,
            "confidence": 95,
            "mutations": [{"type": "CREATE", "node_label": "LitigationHold"}]
        },
        {
            "action": "DRAFT_SETTLEMENT",
            "cost": 100000,
            "risk": 50,
            "time": 30,
            "stability": 80,
            "capability": 50,
            "reversibility": 10,
            "dependency": 20,
            "confidence": 70,
            "mutations": [{"type": "CREATE", "node_label": "SettlementDraft"}]
        }
    ]
    
    RBAC_MATRIX = {
        "INITIATE_LITIGATION_HOLD": ["GeneralCounsel", "LegalOps"],
        "DRAFT_SETTLEMENT": ["GeneralCounsel"]
    }
    
    GRAPH_SCHEMA = ["LitigationHold", "SettlementDraft", "Lawsuit", "CompliancePolicy"]

    def get_rbac_matrix(self) -> Dict[str, List[str]]:
        return self.RBAC_MATRIX

    def get_action_limits(self) -> Dict[str, float]:
        return {"DRAFT_SETTLEMENT": 5000000}

    async def _execute_domain_logic(self, action: str, context: Dict[str, Any], timestamp: str, decision_id: str, prov_id: str) -> Dict[str, Any]:
        action_def = next((a for a in self.AVAILABLE_ACTIONS if a["action"] == action), None)
        if not action_def: return {"result": "FAILED", "reason": "Unknown Action"}
            
        target_id = context.get("target_id", f"gen_{uuid.uuid4().hex[:8]}")
        for mutation in action_def.get("mutations", []):
            if mutation["type"] == "CREATE":
                await self.provider.create_node(mutation["node_label"], {"id": f"{mutation['node_label']}_{uuid.uuid4().hex[:8]}", "created_at": timestamp})
                
        return {"result": "SUCCESS", "target_id": target_id}
