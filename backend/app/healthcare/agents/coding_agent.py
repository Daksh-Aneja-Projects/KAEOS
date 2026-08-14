"""
KAEOS Healthcare — Medical Coding Agent

Suggests ICD-10 / CPT codes for an encounter. Suggestion-only and gated: the
codes are a recommendation for a human coder (always_hitl), never auto-applied
to a claim.
"""
import logging
from typing import Any, Dict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.healthcare.agents.gated_runner import extract_decision, run_gated_healthcare_skill
from app.healthcare.models.core import ClinicalTask, PatientEncounter
from app.services.provenance import append_ledger_event

logger = logging.getLogger(__name__)


class CodingAgent:
    persona = ("You are the KAEOS Medical Coding Agent. You suggest ICD-10 and CPT "
               "codes from an encounter's documented reason. You never finalize a "
               "claim; a certified human coder reviews every suggestion.")

    async def suggest_codes(self, db: AsyncSession, encounter_id: str, tenant_id: str) -> Dict[str, Any]:
        enc = (await db.execute(select(PatientEncounter).where(
            PatientEncounter.id == encounter_id,
            PatientEncounter.tenant_id == tenant_id))).scalar_one_or_none()
        if not enc:
            raise ValueError(f"Encounter {encounter_id} not found")

        # Deterministic work + provenance FIRST: open a coding task tied to the
        # encounter so the suggestion has a tracked, auditable home.
        task = ClinicalTask(tenant_id=tenant_id, encounter_id=enc.id,
                            task_type="coding", status="IN_PROGRESS")
        db.add(task)
        await append_ledger_event(
            db, tenant_id=tenant_id, event_type="CODING_STARTED",
            reasoning=f"Coding suggestion requested for encounter {enc.encounter_number}.",
            scope=enc.id,
        )

        result = await run_gated_healthcare_skill(
            skill_id="hlth_coding_suggest",
            steps=[{"step": 1, "name": "Suggest Codes",
                    "prompt": (f"Encounter {enc.encounter_number} ({enc.encounter_type}); "
                               f"reason: {enc.reason or 'n/a'}. Suggest ICD-10 diagnosis codes. "
                               'Respond as JSON: {"codes": ["F..."], "confidence": 0.0}.')}],
            context={"encounter_id": enc.id},
            tenant_id=tenant_id,
        )

        decision = extract_decision(result) if result.get("status") == "SUCCESS_CLEAN" else {}
        return {"encounter_id": enc.id, "task_id": task.id,
                "status": result.get("status"), "suggested_codes": decision.get("codes"),
                "execution_id": result.get("execution_id")}
