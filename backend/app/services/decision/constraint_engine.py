import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

class DecisionConstraintEngine:
    """
    Evaluates options against Enterprise Constraints.
    Rejects or penalizes options that violate defined boundaries.
    """
    
    def __init__(self, enterprise_graph):
        self.graph = enterprise_graph

    async def evaluate_constraints(self, option: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Evaluates a generated option against all active constraints.
        Returns the option with constraint evaluations appended.
        """
        violations = []
        penalties = 0.0
        
        # 1. Budget Constraint
        cost = option.get("estimated_cost", 0)
        available_budget = context.get("available_budget", float('inf'))
        if cost > available_budget:
            violations.append(f"Budget Violation: Cost {cost} exceeds available {available_budget}")
            penalties += 0.4
            
        # 2. Risk Constraint
        risk_exposure = option.get("risk_score", 0)
        risk_appetite = context.get("risk_appetite", 0.8) # max acceptable risk
        if risk_exposure > risk_appetite:
            violations.append(f"Risk Violation: Exposure {risk_exposure} exceeds appetite {risk_appetite}")
            penalties += 0.3
            
        # 3. Workforce Constraint
        workforce_required = option.get("workforce_required", 0)
        available_workforce = context.get("available_workforce", float('inf'))
        if workforce_required > available_workforce:
            violations.append(f"Workforce Violation: Requires {workforce_required} but only {available_workforce} available")
            penalties += 0.2
            
        # 4. Compliance/Policy Constraint
        is_compliant = option.get("is_compliant", True)
        if not is_compliant:
            violations.append("Policy Violation: Option triggers compliance failure.")
            # Compliance violations are usually immediate rejection
            penalties += 1.0

        is_rejected = penalties >= 1.0
        
        return {
            **option,
            "constraint_violations": violations,
            "constraint_penalty": penalties,
            "is_rejected_by_constraints": is_rejected
        }
