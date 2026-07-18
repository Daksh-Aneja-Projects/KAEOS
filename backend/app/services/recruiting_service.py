import logging
import uuid
from datetime import datetime
from typing import Dict, Any

from app.services.graph.graph_service import GraphService

logger = logging.getLogger(__name__)

class RecruitingService:
    """
    Minimal Execution Service for Twin Truth Sprint 4.
    Listens to approved HR decisions and mutates the Twin Graph directly.
    """
    
    def __init__(self, graph_service: GraphService):
        self.graph_service = graph_service
        self.provider = graph_service.provider
        
    async def get_open_requisitions(self) -> int:
        reqs = 0
        for node in self.provider.nodes.values():
            if node.get("type", "") == "JobRequisition" or node.get("label") == "JobRequisition":
                reqs += 1
            # Or if id contains req_
            elif "req_" in str(node.get("id", "")):
                reqs += 1
        return reqs

    async def execute_action(self, decision: Dict[str, Any]) -> Dict[str, Any]:
        """
        Executes an approved decision.
        """
        action = decision.get("action", "")
        logger.info(f"RecruitingService: Executing approved action: {action}")
        
        if "External Hire" in action or action == "CREATE_JOB_REQUISITION":
            req_id = f"req_{uuid.uuid4().hex[:8]}"
            timestamp = datetime.utcnow().isoformat()
            
            # Extract capabilities that need to be hired from the decision evidence
            decision.get("dimensions", {})
            
            # Mutate the Enterprise Twin
            await self.provider.create_node("JobRequisition", {
                "id": req_id,
                "name": f"Requisition for {action}",
                "status": "OPEN",
                "created_at": timestamp,
                "source_decision_id": decision.get("decision_id", "unknown")
            })
            
            # Create edges to whatever goals or capabilities we're restoring
            # In a real system, we'd extract these from 'impacted_entities'
            
            # Return Provenance Record
            return {
                "decision_id": decision.get("decision_id", "unknown"),
                "action_executed": "CREATE_JOB_REQUISITION",
                "requisition_id": req_id,
                "timestamp": timestamp,
                "result": "SUCCESS",
                "twin_mutated": True
            }
            
        return {"result": "IGNORED", "reason": "Action not supported by RecruitingService"}
