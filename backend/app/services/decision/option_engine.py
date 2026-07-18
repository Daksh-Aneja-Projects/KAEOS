import logging
from typing import Dict, Any, List
import uuid

logger = logging.getLogger(__name__)

class OptionGenerationEngine:
    """
    Tier 1 Fast Option Generation Engine.
    Dynamically synthesizes options based on enterprise event archetypes.
    Target Execution: < 3 seconds.
    """
    
    def __init__(self, enterprise_graph):
        self.graph = enterprise_graph

    async def generate_options(self, event_type: str, target_entity: str, context: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Generates options dynamically derived from Enterprise Graph evidence.
        Analyzes causal paths to identify capability gaps, project risks, and goal impacts.
        """
        logger.info(f"OptionEngine: Generating Tier 1 Fast options for {event_type} on {target_entity}")
        options = []
        
        graph_impacts = context.get("graph_impacts", [])
        
        # 1. Evidence Extraction
        capability_gaps = set()
        goal_impacts = set()
        impacted_projects = set()
        
        for impact in graph_impacts:
            # Extract capabilities from the path nodes
            for _idx, node in enumerate(impact.get("path_nodes", [])):
                if "cap_" in node:
                    # In our structured paths, if the node is cap_, the next relation is often the Team or Project
                    capability_gaps.add(node)
                    
            if impact.get("target_category") == "Goal":
                goal_impacts.add(impact.get("target_node_name"))
            if impact.get("target_category") == "Project":
                impacted_projects.add(impact.get("target_node_name"))
                
        # Base Option Template Builder
        def create_option(action, desc, cost, risk, evidence, recovery):
            return {
                "option_id": str(uuid.uuid4()),
                "action": action,
                "description": desc,
                "estimated_cost": cost,
                "risk_score": risk,
                "evaluation_tier": 1,
                "initial_expected_value": 1.0 - risk - (cost / 1000000.0),
                "initial_decision_quality": ((1.0 - risk) * 0.5) + 0.5,
                # New Traceability Fields
                "supporting_evidence": evidence,
                "impacted_entities": {
                    "goals": list(goal_impacts),
                    "projects": list(impacted_projects)
                },
                "expected_recovery": recovery
            }

        # 2. Dynamic Option Generation based on Evidence
        evidence = "Graph traversal identified systemic impact."
        if capability_gaps:
            caps_str = ", ".join(capability_gaps)
            goals_str = ", ".join(goal_impacts)
            evidence = f"Graph traversal identified loss of capabilities [{caps_str}] causing degradation of goals [{goals_str}]."
        elif goal_impacts:
            evidence = f"Direct impact detected on {list(goal_impacts)}."
            
        available_actions = context.get("available_actions", [])
        if available_actions:
            # Universal Option Generation
            for action_def in available_actions:
                options.append(create_option(
                    action=action_def.get("action_id", "GENERIC_ACTION"),
                    desc=action_def.get("description", f"Execute {action_def.get('name', 'action')}"),
                    cost=action_def.get("base_cost", 10000),
                    risk=action_def.get("base_risk", 0.5),
                    evidence=evidence,
                    recovery=action_def.get("recovery_time", "Standard recovery timeline.")
                ))
        else:
            # Abstract fallback if no department configuration is provided
            options.append(create_option(
                action="Standard Mitigation",
                desc="Apply baseline mitigation protocol.",
                cost=10000,
                risk=0.5,
                evidence=evidence,
                recovery="Localized stabilization."
            ))
            
        return options
