"""AEOS P2 — Organisational Intelligence Layer
Maps the human system — influence networks, change resistance, skills topology.
Not just technology; understands who to influence and how.
"""
import json
import logging

logger = logging.getLogger(__name__)


class OrgIntelligenceEngine:
    """P2 — Human System Cognition.
    
    Capabilities:
    - Org network graph (formal + informal influence)
    - Change resistance heat map
    - Skills topology mapping
    - Change readiness scoring per business unit
    """

    async def score_change_readiness(
        self, department: str, change_description: str,
        tenant_id: str = "default"
    ) -> dict:
        """Real-time change readiness index per business unit."""
        from app.services.llm_router import LLMRouter

        llm = LLMRouter()
        prompt = (
            f"You are the AEOS Organisational Intelligence Engine.\n"
            f"Department: {department}\n"
            f"Proposed change: {change_description}\n\n"
            f"Evaluate change readiness and resistance. Output JSON:\n"
            f"{{\"readiness_score\": 0.0-1.0, \"resistance_level\": \"LOW|MEDIUM|HIGH\", "
            f"\"key_risks\": [\"...\"], \"recommended_engagement_sequence\": [\"...\"], "
            f"\"estimated_adoption_weeks\": int, \"champion_roles\": [\"...\"]}}"
        )

        try:
            res = await llm.complete(prompt=prompt, model_tier="reasoning")
            content = res if isinstance(res, str) else res.get("content", "{}")
            analysis = json.loads(content)
            return {"status": "SCORED", "department": department, **analysis}
        except Exception as e:
            logger.error(f"P2 readiness scoring failed: {e}")
            return {
                "status": "FALLBACK", "department": department,
                "readiness_score": 0.5, "resistance_level": "MEDIUM",
                "key_risks": ["Unable to assess — manual review recommended"],
                "recommended_engagement_sequence": ["Schedule stakeholder briefing"],
                "estimated_adoption_weeks": 8, "champion_roles": ["Department Head"],
            }

    async def map_influence_path(
        self, target_outcome: str, department: str,
        tenant_id: str = "default"
    ) -> dict:
        """P2 — Influence path planner for change initiatives."""
        from app.services.llm_router import LLMRouter

        llm = LLMRouter()
        prompt = (
            f"You are the AEOS Influence Path Planner.\n"
            f"Target outcome: {target_outcome}\n"
            f"Department: {department}\n\n"
            f"Recommend the optimal sequence of stakeholder engagement.\n"
            f"Output JSON: {{\"influence_path\": [{{\"step\": 1, \"stakeholder_role\": \"...\", "
            f"\"action\": \"...\", \"expected_outcome\": \"...\"}}], \"critical_path_weeks\": int}}"
        )

        try:
            res = await llm.complete(prompt=prompt, model_tier="reasoning")
            content = res if isinstance(res, str) else res.get("content", "{}")
            return {"status": "MAPPED", **json.loads(content)}
        except Exception as e:
            logger.error(f"P2 influence mapping failed: {e}")
            return {"status": "FAILED", "error": str(e)}

    async def get_skills_topology(self, tenant_id: str = "default") -> dict:
        """P2 — Skills topology map showing capability gaps and concentrations."""
        from app.core.database import AsyncSessionLocal
        from app.models.domain import Employee
        from sqlalchemy import select, func

        async with AsyncSessionLocal() as db:
            # Aggregate by department and role — scoped to the caller's tenant.
            result = await db.execute(
                select(Employee.department, Employee.role, func.count(Employee.id))
                .where(Employee.tenant_id == tenant_id)
                .group_by(Employee.department, Employee.role)
            )
            topology = {}
            for dept, role, count in result.all():
                dept_key = dept or "Unknown"
                if dept_key not in topology:
                    topology[dept_key] = {"roles": {}, "total": 0}
                topology[dept_key]["roles"][role or "IC"] = count
                topology[dept_key]["total"] += count

        return {"topology": topology, "status": "MAPPED"}
