"""KAEOS Support Domain - SLA Monitor Agent

Context-grounding: the agent loads real records and reasons over their
content. Passing only opaque ids left the model reasoning over identifiers
(confirmed ungrounded on real onboarded data), so facts are non-optional.
"""
from typing import Any, Dict

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.support.agents.gated_runner import run_gated_support_skill
from app.support.models.sla import SLABreach, SLAPolicy
from app.services.json_utils import plain_facts


class SLAAgent:
    async def check_sla(self, db: AsyncSession, tenant_id: str) -> Dict[str, Any]:
        policies = (await db.execute(
            select(SLAPolicy).where(
                SLAPolicy.tenant_id == tenant_id, SLAPolicy.is_active == True  # noqa: E712
            )
        )).scalars().all()
        breaches = (await db.execute(
            select(SLABreach).where(SLABreach.tenant_id == tenant_id)
            .order_by(desc(SLABreach.created_at)).limit(20)
        )).scalars().all()

        facts = {
            "active_policies": [
                {"name": p.name, "priority_level": p.priority_level,
                 "response_target_mins": p.response_target_mins,
                 "resolution_target_hrs": p.resolution_target_hrs}
                for p in policies
            ],
            "recent_breaches": [
                {"breach_type": b.breach_type, "minutes_over": b.minutes_over,
                 "acknowledged": b.is_acknowledged}
                for b in breaches
            ],
            "unacknowledged_count": sum(1 for b in breaches if not b.is_acknowledged),
        }
        facts = plain_facts(facts)
        return await run_gated_support_skill(
            skill_id="support_sla_monitor",
            steps=[{"step": 1, "name": "Check",
                    "prompt": f"Review SLA posture from these policies and recent breaches: {facts}"}],
            context={
                "tenant_id": tenant_id, **facts,
                "instruction": "Output strict JSON: {sla_health, worst_breaches, actions}.",
            },
            tenant_id=tenant_id,
        )
