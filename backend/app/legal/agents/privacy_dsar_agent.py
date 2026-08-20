"""KAEOS Legal Domain - Privacy DSAR Agent

Context-grounding: the agent loads the real entity and reasons over its
content. Passing only an opaque id left the model classifying an identifier
(confirmed ungrounded on real onboarded data), so facts are non-optional.
"""
import logging
from typing import Any, Dict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.legal.agents.gated_runner import run_gated_legal_skill, extract_decision
from app.legal.models.privacy import DataSubjectRequest, DsarStatus
from app.services.json_utils import enum_value, plain_facts
from app.models.execution_status import ExecutionStatus

logger = logging.getLogger(__name__)


class PrivacyDSARAgent:
    async def process_dsar(self, db: AsyncSession, dsar_id: str, tenant_id: str) -> Dict[str, Any]:
        logger.info(f"PrivacyDSARAgent processing DSAR {dsar_id}")
        dsar = (await db.execute(
            select(DataSubjectRequest).where(
                DataSubjectRequest.id == dsar_id,
                DataSubjectRequest.tenant_id == tenant_id,
            )
        )).scalar_one_or_none()
        if not dsar:
            raise ValueError(f"DSAR {dsar_id} not found")

        facts = {
            "request_type": enum_value(dsar.request_type),
            "status": enum_value(dsar.status),
            "request_date": str(dsar.request_date) if dsar.request_date else None,
            "deadline_date": str(dsar.deadline_date) if dsar.deadline_date else None,
            "assigned_officer": dsar.assigned_officer,
            "prior_validation": dsar.ai_validation,
        }
        facts = plain_facts(facts)
        steps = [
            {"step": 1, "name": "Locate Records",
             "prompt": f"Plan the record location for this data subject request: {facts}"},
            {"step": 2, "name": "Produce Response",
             "prompt": "Generate a GDPR 30-day compliant response plan for the request."},
        ]
        result = await run_gated_legal_skill(
            skill_id="legal_privacy_dsar",
            steps=steps,
            context={
                "dsar_id": dsar_id, "tenant_id": tenant_id, **facts,
                # GDPR Gate-6 lawful basis: fulfilling a data-subject request is
                # processing to comply with a legal obligation (Art.12/15-22).
                "legal_basis": "legal_obligation:data_subject_request",
                "instruction": "Output strict JSON: {response_plan, systems_to_query, deadline_risk}.",
            },
            tenant_id=tenant_id,
            compliance_tags=["GDPR", "CCPA"],
        )
        if result.get("status") == ExecutionStatus.PENDING_HITL:
            return {"status": ExecutionStatus.PENDING_HITL, "dsar_id": dsar_id, "execution_id": result.get("execution_id")}
        if result.get("status") == ExecutionStatus.SUCCESS_CLEAN:
            decision = extract_decision(result)

            # The agent produced a validated response plan for this request -
            # record that (dsar.ai_validation) and advance a freshly RECEIVED
            # request into PROCESSING. Never downgrade or skip past a status a
            # human already moved forward (e.g. COMPLETED).
            if decision.get("response_plan"):
                dsar.ai_validation = True
                if dsar.status == DsarStatus.RECEIVED:
                    dsar.status = DsarStatus.PROCESSING

            db.add(dsar)
            await db.commit()

            return {
                "status": "success",
                "dsar_id": dsar_id,
                "decision": decision,
                "execution_id": result.get("execution_id"),
            }
        return result
