"""KAEOS Operations Domain - QA Inspection Agent

Context-grounding: the agent loads the real entity and reasons over its
content. Passing only an opaque id left the model classifying an identifier
(confirmed ungrounded on real onboarded data), so facts are non-optional.
"""
from typing import Any, Dict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.operations.agents.gated_runner import run_gated_operations_skill
from app.operations.models.quality import Inspection
from app.services.json_utils import plain_facts


def _v(x):
    return getattr(x, "value", x)


class QAAgent:
    async def inspect_qa(self, db: AsyncSession, inspection_id: str, tenant_id: str) -> Dict[str, Any]:
        insp = (await db.execute(
            select(Inspection).where(
                Inspection.id == inspection_id, Inspection.tenant_id == tenant_id
            )
        )).scalar_one_or_none()
        if not insp:
            raise ValueError(f"Inspection {inspection_id} not found")

        facts = {
            "inspected_item": insp.inspected_item,
            "inspector": insp.inspector,
            "status": _v(insp.status),
            "notes": (insp.notes or "")[:1000],
            "standard_id": insp.standard_id,
        }
        facts = plain_facts(facts)
        return await run_gated_operations_skill(
            skill_id="operations_qa_inspect",
            steps=[{"step": 1, "name": "Inspect",
                    "prompt": f"Review this QA inspection record and assess quality outcome: {facts}"}],
            context={
                "inspection_id": inspection_id, "tenant_id": tenant_id, **facts,
                "instruction": "Output strict JSON: {pass_or_fail, defects, corrective_actions}.",
            },
            tenant_id=tenant_id,
        )
