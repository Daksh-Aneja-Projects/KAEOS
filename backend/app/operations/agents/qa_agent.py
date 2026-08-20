"""KAEOS Operations Domain - QA Inspection Agent

Context-grounding: the agent loads the real entity and reasons over its
content. Passing only an opaque id left the model classifying an identifier
(confirmed ungrounded on real onboarded data), so facts are non-optional.
"""
from typing import Any, Dict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.operations.agents.gated_runner import extract_decision, run_gated_operations_skill
from app.operations.models.quality import Inspection, QualityStatus
from app.services.json_utils import enum_value, plain_facts
from app.models.execution_status import ExecutionStatus


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
            "status": enum_value(insp.status),
            "notes": (insp.notes or "")[:1000],
            "standard_id": insp.standard_id,
        }
        facts = plain_facts(facts)
        result = await run_gated_operations_skill(
            skill_id="operations_qa_inspect",
            steps=[{"step": 1, "name": "Inspect",
                    "prompt": f"Review this QA inspection record and assess quality outcome: {facts}"}],
            context={
                "inspection_id": inspection_id, "tenant_id": tenant_id, **facts,
                "instruction": "Output strict JSON: {pass_or_fail, defects, corrective_actions}.",
            },
            tenant_id=tenant_id,
        )

        if result.get("status") == ExecutionStatus.SUCCESS_CLEAN:
            decision = extract_decision(result)
            verdict = decision.get("pass_or_fail")
            if isinstance(verdict, str):
                v = verdict.strip().upper()
                if v in ("PASS", "PASSED"):
                    insp.status = QualityStatus.PASSED
                elif v in ("FAIL", "FAILED"):
                    insp.status = QualityStatus.FAILED
                # any other value (e.g. "INCONCLUSIVE") leaves status untouched —
                # an unrecognized verdict must not silently overwrite real state.

            note_parts = []
            defects = decision.get("defects")
            if defects:
                defects_text = defects if isinstance(defects, str) else ", ".join(str(d) for d in defects)
                if defects_text.strip():
                    note_parts.append(f"Defects noted: {defects_text}.")
            actions = decision.get("corrective_actions")
            if actions:
                actions_text = actions if isinstance(actions, str) else ", ".join(str(a) for a in actions)
                if actions_text.strip():
                    note_parts.append(f"Corrective actions: {actions_text}.")
            insp.ai_summary = " ".join(note_parts) if note_parts else None
            db.add(insp)
            await db.commit()
            result = {**result, "decision": decision}

        return result
