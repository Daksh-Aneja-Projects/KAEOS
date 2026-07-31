from typing import Dict, Any

class FeedbackEngine:
    """L10 - Closed-Loop Feedback & Active Learning Engine"""
    
    async def process_agent_outcome(self, execution_data: Dict[str, Any]) -> Dict[str, Any]:
        """Processes agent outcomes to adjust confidence and trigger learning."""
        status = execution_data.get("status")
        execution_data.get("rule_id")
        
        if status == "SUCCESS_CLEAN":
            # Increase confidence
            return {"confidence_delta": 0.05, "action": "UPDATE_KB"}
        elif status == "HUMAN_OVERRIDDEN":
            # Significant confidence drop, trigger elicitation
            return {"confidence_delta": -0.30, "action": "TRIGGER_ELICITATION"}
            
        return {"action": "NONE"}
