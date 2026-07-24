"""
KAEOS Enterprise Scorecard Engine
Evaluates health across the Enterprise Purpose Layer and Operational Layer by
combining live domain State (StateService) with the real Enterprise Graph
(GraphService.snapshot) — specifically the Risk -> THREATENS edges that pull down
the health of the goals/initiatives/projects/vendors they point at.

Previously this returned hardcoded dimension constants with a "in a real
implementation we would query the graph" comment. It now queries the graph.
"""

import logging
from collections import defaultdict
from typing import Any, Dict

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.graph.graph_service import GraphService
from app.services.state.state_service import StateService

logger = logging.getLogger(__name__)

_SEVERITY_WEIGHT = {"CRITICAL": 1.0, "HIGH": 0.6, "MEDIUM": 0.3, "LOW": 0.1}


class ScorecardEngine:
    def __init__(self, graph_service: GraphService):
        self.graph = graph_service

    async def calculate_enterprise_scorecard(self, db: AsyncSession, tenant_id: str) -> Dict[str, Any]:
        logger.info(f"ScorecardEngine: Calculating enterprise scorecard for {tenant_id}")

        # 1. Live domain state (real DB-backed health scores)
        hr_state = await StateService.get_state(db, tenant_id, "hr")
        fin_state = await StateService.get_state(db, tenant_id, "finance")
        ops_state = await StateService.get_state(db, tenant_id, "operations")

        hr_health = float(getattr(hr_state, "hr_health_score", None) or 1.0)
        fin_health = float(getattr(fin_state, "financial_health_score", None) or 1.0)
        ops_health = float(getattr(ops_state, "ops_health_score", None) or 1.0)

        # 2. Real graph: aggregate Risk -> THREATENS pressure per entity category
        nodes: Dict[str, Any] = {}
        edges = []
        try:
            nodes, edges = await self.graph.snapshot()
        except Exception as exc:
            logger.warning("ScorecardEngine: graph snapshot unavailable (%s); scoring on state only.", exc)

        count: Dict[str, int] = defaultdict(int)
        for node in nodes.values():
            count[node.get("label", "Unknown")] += 1

        threat: Dict[str, float] = defaultdict(float)
        critical_risks = 0
        total_risks = count.get("Risk", 0)
        for e in edges:
            if e.get("type") != "THREATENS":
                continue
            risk = nodes.get(e.get("source"), {})
            sev = str(risk.get("severity", "MEDIUM")).upper()
            if sev == "CRITICAL":
                critical_risks += 1
            target = nodes.get(e.get("target"))
            if target:
                threat[target.get("label", "Unknown")] += _SEVERITY_WEIGHT.get(sev, 0.3)

        def graph_health(label: str) -> float:
            c = count.get(label, 0)
            if not c:
                return 1.0
            return round(1.0 - min(1.0, threat.get(label, 0.0) / c), 2)

        goal_health = graph_health("Goal")
        initiative_health = graph_health("Initiative")
        project_graph_health = graph_health("Project")
        vendor_health = graph_health("Vendor")
        risk_health = round(1.0 - (critical_risks / total_risks), 2) if total_risks else 1.0

        # Department coverage: fraction possessing a capability (real structural signal)
        dept_total = count.get("Department", 0)
        depts_with_cap = {e["source"] for e in edges
                          if e.get("type") == "POSSESSES_CAPABILITY"
                          and nodes.get(e.get("source"), {}).get("label") == "Department"}
        department_health = round(len(depts_with_cap) / dept_total, 2) if dept_total else 1.0

        # Combine graph + operational state where both bear on a dimension
        project_health = round(min(project_graph_health, ops_health), 2)
        # Objective/Program sit structurally between goals and initiatives
        objective_health = round((goal_health + initiative_health) / 2, 2)
        program_health = round((initiative_health + project_health) / 2, 2)

        dimensions = {
            "Goal_Health": goal_health,
            "Objective_Health": objective_health,
            "Initiative_Health": initiative_health,
            "Program_Health": program_health,
            "Project_Health": project_health,
            "Department_Health": department_health,
            "Workforce_Health": round(hr_health, 2),
            "Vendor_Health": vendor_health,
            "Risk_Health": risk_health,
        }

        overall = round((hr_health + fin_health + ops_health) / 3, 2)

        return {
            "overall_health": overall,
            "dimensions": dimensions,
            "graph_size": {"nodes": len(nodes), "edges": len(edges)},
            "explanation": (
                f"Overall from live HR/Finance/Ops state; dimension health derived from "
                f"{total_risks} risk node(s) threatening {len(nodes)} graph entities "
                f"({critical_risks} critical)."
            ),
        }
