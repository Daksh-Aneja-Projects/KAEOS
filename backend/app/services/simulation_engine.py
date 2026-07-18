"""
KAEOS Enterprise Simulation Engine
Phase 7
Supports complex scenario modeling (Hiring Freeze, Revenue Decline, etc.)
Outputs Impact Maps, Risk Scores, Financial Impact, Timeline Impact.
"""

import logging
from typing import Dict, Any

from sqlalchemy.ext.asyncio import AsyncSession
from app.services.graph.graph_service import GraphService
from app.services.state.state_service import StateService

logger = logging.getLogger(__name__)


class EnterpriseSimulationEngine:
    
    def __init__(self, graph_service: GraphService):
        self.graph = graph_service

    async def run_scenario(self, db: AsyncSession, tenant_id: str, scenario_type: str, parameters: dict) -> Dict[str, Any]:
        """
        Runs a simulation for a specific scenario type.
        scenario_types: HIRING_FREEZE, REVENUE_DECLINE, VENDOR_FAILURE, BUDGET_REDUCTION, PROJECT_DELAY
        """
        logger.info(f"SimulationEngine: Running {scenario_type} for {tenant_id}")
        
        # 1. Fetch current baseline state
        hr_state = await StateService.get_state(db, tenant_id, "hr")
        fin_state = await StateService.get_state(db, tenant_id, "finance")
        ops_state = await StateService.get_state(db, tenant_id, "operations")
        
        # 2. Simulate impacts based on scenario type
        if scenario_type == "HIRING_FREEZE":
            result = await self._simulate_hiring_freeze(db, tenant_id, parameters, hr_state, ops_state)
        elif scenario_type == "REVENUE_DECLINE":
            result = await self._simulate_revenue_decline(db, tenant_id, parameters, fin_state)
        elif scenario_type == "VENDOR_FAILURE":
            result = await self._simulate_vendor_failure(db, tenant_id, parameters, ops_state)
        else:
            raise ValueError(f"Unknown scenario type: {scenario_type}")
            
        return {
            "scenario": scenario_type,
            "parameters": parameters,
            "results": result
        }

    async def _simulate_hiring_freeze(self, db, tenant_id, params, hr_state, ops_state):
        duration_months = params.get("duration_months", 6)
        
        # Baseline math
        current_attrition = getattr(hr_state, "attrition_rate", 0.10) if hr_state else 0.10
        getattr(ops_state, "active_projects", 50) if ops_state else 50
        
        # Simulated cascade
        headcount_loss = int(duration_months * (current_attrition / 12) * 1000) # Example 1000 HC base
        projects_at_risk_increase = int(headcount_loss * 0.4)
        
        # Graph query to find specific critical projects impacted by unfilled open reqs
        # (Mocked graph traversal for unfilled roles -> projects)
        impact_map = [
            {"node": "Project_Alpha", "risk": "CRITICAL", "reason": "Missing Lead Engineer"},
            {"node": "Project_Beta", "risk": "HIGH", "reason": "Capacity reduced by 30%"}
        ]
        
        return {
            "impact_map": impact_map,
            "financial_impact": {"savings": headcount_loss * 12000, "opportunity_cost": projects_at_risk_increase * 50000},
            "timeline_impact": f"Average project delay: {duration_months * 0.5} months",
            "risk_score": 0.75,
            "recommended_actions": [
                "Reallocate engineers from Project Beta to Project Alpha",
                "Automate 15% of support tasks to free capacity"
            ]
        }

    async def _simulate_revenue_decline(self, db, tenant_id, params, fin_state):
        decline_pct = params.get("decline_pct", 0.20)
        
        # Simulated cascade
        return {
            "impact_map": [{"node": "Q3_Goals", "risk": "CRITICAL"}],
            "financial_impact": {"arr_loss": 5000000 * decline_pct},
            "timeline_impact": "Runway reduced by 4 months",
            "risk_score": 0.88,
            "recommended_actions": [
                "Execute 10% budget reduction in Marketing",
                "Pause non-critical vendor contracts"
            ]
        }
        
    async def _simulate_vendor_failure(self, db, tenant_id, params, ops_state):
        vendor_id = params.get("vendor_id")
        
        # Calculate true blast radius in the Graph
        impacts = await self.graph.get_impact_radius(vendor_id, depth=3) if vendor_id else []
        
        return {
            "impact_map": impacts,
            "financial_impact": {"cost_to_replace": 150000},
            "timeline_impact": "Supply chain delay of 14 days",
            "risk_score": 0.92,
            "recommended_actions": [
                "Activate fallback vendor B",
                "Notify impacted enterprise customers immediately"
            ]
        }
