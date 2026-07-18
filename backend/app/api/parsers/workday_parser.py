import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

class WorkdayEventParser:
    def parse(self, raw_payload: Dict[str, Any]) -> Dict[str, Any]:
        logger.info("WorkdayEventParser: Transforming raw payload to canonical event.")
        
        # Simulate mapping from a complex raw Workday object to a simple KAEOS struct
        canonical = {
            "canonical_event_type": "EMPLOYEE_TERMINATION",
            "employee_id": raw_payload.get("worker_id"),
            "department": raw_payload.get("department", "Unknown"),
            "termination_date": raw_payload.get("termination_date"),
            "manager": raw_payload.get("manager_id"),
            "role": raw_payload.get("role", "Employee")
        }
        
        # Validation
        for req in ["employee_id", "termination_date"]:
            if not canonical[req]:
                raise ValueError(f"Missing required canonical field: {req}")
                
        return canonical
