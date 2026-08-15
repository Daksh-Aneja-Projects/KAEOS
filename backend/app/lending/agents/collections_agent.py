"""
KAEOS Lending Domain - Collections Agent

Attempts a debt-collection contact on a delinquent serviced loan. Routes the
action through the 7-gate governance pipeline (Compliance -> Fairness -> HITL
-> Debate -> Execute -> Audit) with the FDCPA compliance tag; the LLM step
only drafts a compliant contact note for the human collector, it never
decides whether the contact is permitted. The BINDING decision is the
deterministic FDCPA gate in
app.lending.services.servicing.attempt_collection_contact - a blocking
verdict there fails closed and nothing is persisted, mirroring how the
Underwriter Agent defers to the real ECOA/FAIR_LENDING gate.
"""
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.lending.agents.gated_runner import extract_decision, run_gated_lending_skill
from app.lending.services.servicing import (attempt_collection_contact,
                                             load_collection_case)

logger = logging.getLogger(__name__)


class CollectionsAgent:
    def __init__(self):
        self.persona = (
            "You are the KAEOS Collections Agent. You draft a short, "
            "professional debt-collection contact note for a human collector. "
            "You never threaten, harass, or misrepresent the debt, and you "
            "never authorize a contact yourself - the FDCPA gate does."
        )

    async def contact(
        self, db: AsyncSession, case_id: str, tenant_id: str, *,
        hour_local: int, channel: str = "phone", harassment: bool = False,
        notes: Optional[str] = None, actor: str,
    ) -> Dict[str, Any]:
        case = await load_collection_case(db, tenant_id, case_id)
        now = datetime.now(timezone.utc)
        opened = case.opened_at or now
        if opened.tzinfo is None:
            opened = opened.replace(tzinfo=timezone.utc)
        days_since_initial = max(0, (now - opened).days)

        collection_ctx = {
            "communications": [{"hour_local": hour_local}],
            "harassment": bool(harassment),
            "validation_notice_sent": bool(case.validation_notice_sent),
            "days_since_initial": days_since_initial,
        }

        steps = [{
            "step": 1,
            "name": "Draft Collection Contact Note",
            "prompt": (
                f"Draft a short, professional, compliant debt-collection contact "
                f"note for case {case.id} via {channel} at {hour_local:02d}:00 "
                "local time. Never threaten, harass, or misrepresent the debt "
                "amount or consequences. Return JSON "
                "{\"rationale\": str, \"confidence\": number}."),
        }]

        context = {
            "case_id": case.id,
            "collection": collection_ctx,
            "has_human_approver": bool(actor),
        }

        result = await run_gated_lending_skill(
            skill_id="lending_collection_contact", steps=steps, context=context,
            tenant_id=tenant_id, compliance_tags=["FDCPA"], confidence=0.9)

        status = result.get("status")
        if status == "PENDING_HITL":
            return {"status": "PENDING_HITL", "case_id": case.id,
                    "execution_id": result.get("execution_id"),
                    "reason": "Collection contact requires human approval."}

        if status in ("BLOCKED_COMPLIANCE", "BLOCKED_FAIRNESS", "BLOCKED_DEBATE"):
            logger.warning("CollectionsAgent: case %s blocked by %s", case_id, status)
            return result

        # Clean gate pass -> persist through the REAL fail-closed FDCPA gate.
        updated = await attempt_collection_contact(
            db, tenant_id, case_id=case.id, hour_local=hour_local, channel=channel,
            harassment=harassment, notes=notes, actor=actor)

        rationale = extract_decision(result)
        return {
            "status": "success",
            "case_id": case.id,
            "contact_log": updated.contact_log,
            "rationale": rationale.get("rationale"),
            "execution_id": result.get("execution_id"),
        }
