"""
KAEOS Healthcare — Prior Authorization Agent

Prepares a payer prior-authorization request for a clinical task. Gated: the
recommendation is drafted for a human, never auto-submitted to a payer.
"""
import logging
import uuid
from typing import Any, Dict, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.workflow import apply_transition
from app.healthcare.agents.gated_runner import extract_decision, run_gated_healthcare_skill
from app.healthcare.models.core import ClinicalTask, PatientEncounter
from app.healthcare.services.workflows import CLINICAL_TASK_WORKFLOW
from app.services.provenance import append_ledger_event

logger = logging.getLogger(__name__)


class PriorAuthAgent:
    persona = ("You are the KAEOS Prior Authorization Agent. You assemble the "
               "clinical justification a payer needs to authorize a procedure. A "
               "human reviews and submits; you never file with a payer directly.")

    async def prepare_prior_auth(
        self, db: AsyncSession, tenant: dict, *,
        encounter_id: str, procedure: str, payer: Optional[str] = None,
    ) -> Dict[str, Any]:
        tenant_id = tenant["tenant_id"]
        enc = (await db.execute(select(PatientEncounter).where(
            PatientEncounter.id == encounter_id,
            PatientEncounter.tenant_id == tenant_id))).scalar_one_or_none()
        if not enc:
            raise ValueError(f"Encounter {encounter_id} not found")

        task_id = str(uuid.uuid4())
        task = ClinicalTask(id=task_id, tenant_id=tenant_id, encounter_id=enc.id,
                            task_type="prior_auth", detail={"procedure": procedure, "payer": payer})
        db.add(task)
        await apply_transition(db, CLINICAL_TASK_WORKFLOW, task_id, "IN_PROGRESS", tenant,
                               note=f"Prior-auth prep started for '{procedure}'")

        await append_ledger_event(
            db, tenant_id=tenant_id, event_type="PRIOR_AUTH_STARTED",
            reasoning=f"Prior-auth prep for '{procedure}' on encounter {enc.encounter_number}.",
            scope=enc.id,
        )

        result = await run_gated_healthcare_skill(
            skill_id="hlth_prior_auth",
            steps=[{"step": 1, "name": "Draft Justification",
                    "prompt": (f"Draft a prior-authorization clinical justification for "
                               f"'{procedure}' (encounter {enc.encounter_number}, reason "
                               f"{enc.reason or 'n/a'}). Recommend SUBMIT or MORE_INFO.")}],
            context={"encounter_id": enc.id, "procedure": procedure},
            tenant_id=tenant_id,
        )
        decision = extract_decision(result) if result.get("status") == "SUCCESS_CLEAN" else {}
        return {"encounter_id": enc.id, "task_id": task_id,
                "status": result.get("status"),
                "recommendation": decision.get("recommendation"),
                "execution_id": result.get("execution_id")}
