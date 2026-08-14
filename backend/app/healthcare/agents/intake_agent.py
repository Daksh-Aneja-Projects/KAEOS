"""
KAEOS Healthcare — Intake Agent

Triages a patient encounter: deterministic priority FIRST (never taken from an
LLM), signed to the ledger, then routed through the gated 7-gate pipeline.
"""
import logging
from typing import Any, Dict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.healthcare.agents.gated_runner import run_gated_healthcare_skill
from app.healthcare.models.core import PatientEncounter
from app.services.provenance import append_ledger_event

logger = logging.getLogger(__name__)

# Deterministic triage: keyword -> priority. A missing/unknown reason stays the
# stricter ROUTINE-with-review, never silently EMERGENT or dropped.
_EMERGENT = ("chest pain", "stroke", "unresponsive", "hemorrhage", "sepsis",
             "difficulty breathing", "anaphylaxis", "overdose")
_URGENT = ("fracture", "high fever", "severe", "laceration", "dehydration")


def _triage_priority(reason: str) -> str:
    r = (reason or "").lower()
    if any(k in r for k in _EMERGENT):
        return "EMERGENT"
    if any(k in r for k in _URGENT):
        return "URGENT"
    return "ROUTINE"


class IntakeAgent:
    persona = ("You are the KAEOS Healthcare Intake Agent. You triage encounters "
               "for urgency and completeness before clinical work begins.")

    async def triage_encounter(self, db: AsyncSession, encounter_id: str, tenant_id: str) -> Dict[str, Any]:
        enc = (await db.execute(select(PatientEncounter).where(
            PatientEncounter.id == encounter_id,
            PatientEncounter.tenant_id == tenant_id))).scalar_one_or_none()
        if not enc:
            raise ValueError(f"Encounter {encounter_id} not found")

        priority = _triage_priority(enc.reason)
        enc.priority = priority
        enc.status = "TRIAGED"
        db.add(enc)
        await append_ledger_event(
            db, tenant_id=tenant_id, event_type="ENCOUNTER_TRIAGED",
            reasoning=f"Encounter {enc.encounter_number} triaged {priority} (deterministic).",
            scope=enc.id,
        )

        result = await run_gated_healthcare_skill(
            skill_id="hlth_intake_triage",
            steps=[{"step": 1, "name": "Summarize Triage",
                    "prompt": f"Encounter {enc.encounter_number} ({enc.encounter_type}); "
                              f"deterministic priority {priority}. Write a one-line intake note."}],
            context={"encounter_id": enc.id, "priority": priority},
            tenant_id=tenant_id,
        )
        return {"encounter_id": enc.id, "priority": priority,
                "status": result.get("status"), "execution_id": result.get("execution_id")}
