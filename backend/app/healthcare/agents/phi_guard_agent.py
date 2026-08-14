"""
KAEOS Healthcare — PHI Guard Agent

Evaluates an outbound PHI disclosure against the HIPAA_MINIMUM_NECESSARY,
HIPAA_AUTHORIZATION and PART2 checkers as REAL gates, then routes through the
gated 7-gate pipeline. Fail-closed: a disclosure that a checker BLOCKs is
never recorded - the service refuses it and the ledger holds the denial.
"""
import logging
from typing import Any, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.healthcare.agents.gated_runner import run_gated_healthcare_skill
from app.healthcare.services.phi_disclosure import (
    PHIDisclosureError, build_context, evaluate_disclosure, record_disclosure,
)

logger = logging.getLogger(__name__)

PHI_TAGS = ["HIPAA_MINIMUM_NECESSARY", "HIPAA_AUTHORIZATION", "PART2"]


class PHIGuardAgent:
    persona = ("You are the KAEOS PHI Governance Agent. You ensure every disclosure "
               "is limited to the minimum necessary fields and backed by a valid "
               "patient authorization or specific Part 2 consent when required.")

    async def review_disclosure(
        self,
        db: AsyncSession,
        tenant_id: str,
        *,
        purpose: str,
        recipient: str,
        fields: List[str],
        minimum_necessary_justification: str,
        encounter_id: Optional[str] = None,
        authorization: Optional[dict] = None,
        diagnosis_codes: Optional[List[str]] = None,
        part2_records: bool = False,
        part2_consent: Optional[dict] = None,
        recorded_by: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Deterministic gate FIRST (the load-bearing control), then the gated
        pipeline for governance + provenance. Records only on a clean gate."""
        context = build_context(
            purpose=purpose, fields=fields, authorization=authorization,
            diagnosis_codes=diagnosis_codes, part2_records=part2_records,
            part2_consent=part2_consent,
        )
        verdict = evaluate_disclosure(context)

        if not verdict["verified"]:
            # Fail-closed: refuse via the service (writes the denial to the
            # ledger and raises). Return a structured BLOCKED result.
            try:
                await record_disclosure(
                    db, tenant_id, purpose=purpose, recipient=recipient, fields=fields,
                    minimum_necessary_justification=minimum_necessary_justification,
                    encounter_id=encounter_id, authorization=authorization,
                    diagnosis_codes=diagnosis_codes, part2_records=part2_records,
                    part2_consent=part2_consent, recorded_by=recorded_by,
                )
            except PHIDisclosureError as e:
                return {"status": "BLOCKED_COMPLIANCE", "recorded": False,
                        "reason": str(e), "blocking": e.blocking}
            # Unreachable: an unverified verdict always raises above.
            return {"status": "BLOCKED_COMPLIANCE", "recorded": False}

        # Clean gate: run the governance pipeline (compliance gate re-checks the
        # same tags; always_hitl routes it to a human), then persist.
        gated = await run_gated_healthcare_skill(
            skill_id="hlth_phi_disclosure_review",
            steps=[{"step": 1, "name": "Confirm Disclosure",
                    "prompt": f"Confirm the minimum-necessary disclosure to {recipient} for {purpose}."}],
            context={"encounter_id": encounter_id, "phi_disclosure": context["phi_disclosure"],
                     "authorization": context["authorization"],
                     "part2_records": context["part2_records"],
                     "part2_consent": context["part2_consent"]},
            tenant_id=tenant_id,
            compliance_tags=PHI_TAGS,
        )
        # A hard governance BLOCK (fairness/debate/compliance re-check) must not
        # still persist the disclosure. PENDING_HITL is the normal outcome for
        # this always-HITL skill and DOES record (the deterministic HIPAA gate
        # above already passed); the human approval is the overlay, surfaced via
        # gate_status.
        gate_status = gated.get("status") or ""
        if gate_status.startswith("BLOCKED"):
            return {"status": gate_status, "recorded": False,
                    "reason": "PHI disclosure blocked at the governance gate.",
                    "gate_status": gate_status, "execution_id": gated.get("execution_id")}
        disclosure = await record_disclosure(
            db, tenant_id, purpose=purpose, recipient=recipient, fields=fields,
            minimum_necessary_justification=minimum_necessary_justification,
            encounter_id=encounter_id, authorization=authorization,
            diagnosis_codes=diagnosis_codes, part2_records=part2_records,
            part2_consent=part2_consent, recorded_by=recorded_by,
        )
        return {"status": "RECORDED", "recorded": True, "disclosure_id": disclosure.id,
                "gate_status": gate_status, "execution_id": gated.get("execution_id")}
