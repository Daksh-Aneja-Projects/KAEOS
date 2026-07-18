import logging
import uuid
from typing import Dict, Any, List
from app.services.department_runtime_base import DepartmentRuntimeBase

logger = logging.getLogger(__name__)

class HRRuntimeService(DepartmentRuntimeBase):
    OBSERVED_EVENTS = ["EMPLOYEE_RESIGNED", "CAPABILITY_LOST", "SALARY_BENCHMARK_CHANGED"]
    
    AVAILABLE_ACTIONS = [
        {
            "action": "CREATE_JOB_REQUISITION",
            "cost": 150000,
            "risk": 30,
            "time": 60,
            "stability": 80,
            "capability": 90,
            "reversibility": 10,
            "dependency": 10,
            "confidence": 70,
            "mutations": [{"type": "CREATE", "node_label": "JobRequisition"}]
        },
        {
            "action": "HIRE_CANDIDATE",
            "cost": 5000,
            "risk": 50,
            "time": 14,
            "stability": 90,
            "capability": 95,
            "reversibility": 5,
            "dependency": 5,
            "confidence": 80,
            "mutations": [{"type": "CREATE", "node_label": "Employee"}]
        }
    ]
    
    RBAC_MATRIX = {
        "CREATE_JOB_REQUISITION": ["HRBP", "Executive"],
        "HIRE_CANDIDATE": ["HRBP", "Executive"]
    }
    
    GRAPH_SCHEMA = ["JobRequisition", "Employee", "Skill", "Department"]

    def get_rbac_matrix(self) -> Dict[str, List[str]]:
        return self.RBAC_MATRIX

    def get_action_limits(self) -> Dict[str, float]:
        return {"HIRE_CANDIDATE": 1000000}

    async def _execute_domain_logic(self, action: str, context: Dict[str, Any], timestamp: str, decision_id: str, prov_id: str) -> Dict[str, Any]:
        # Purely abstract mutation logic. Zero domain knowledge.
        action_def = next((a for a in self.AVAILABLE_ACTIONS if a["action"] == action), None)
        if not action_def:
            return {"result": "FAILED", "reason": "Unknown Action"}
            
        target_id = context.get("target_id", f"gen_{uuid.uuid4().hex[:8]}")
        for mutation in action_def.get("mutations", []):
            if mutation["type"] == "CREATE":
                await self.provider.create_node(mutation["node_label"], {"id": f"{mutation['node_label']}_{uuid.uuid4().hex[:8]}", "created_at": timestamp})
                
        return {"result": "SUCCESS", "target_id": target_id}
