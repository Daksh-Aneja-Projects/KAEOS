"""KAEOS Operations Domain - Procurement Audit Agent

Context-grounding: the agent loads the real entity and reasons over its
content. Passing only an opaque id left the model classifying an identifier
(confirmed ungrounded on real onboarded data), so facts are non-optional.
"""
from typing import Any, Dict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.operations.agents.gated_runner import extract_decision, run_gated_operations_skill
from app.operations.models.procurement import PurchaseRequest
from app.services.json_utils import enum_value, plain_facts


class ProcurementAgent:
    async def audit_request(self, db: AsyncSession, request_id: str, tenant_id: str) -> Dict[str, Any]:
        req = (await db.execute(
            select(PurchaseRequest).where(
                PurchaseRequest.id == request_id, PurchaseRequest.tenant_id == tenant_id
            )
        )).scalar_one_or_none()
        if not req:
            raise ValueError(f"Purchase request {request_id} not found")

        facts = {
            "item_description": (req.item_description or "")[:800],
            "quantity": req.quantity,
            "unit_price": req.unit_price,
            "total_estimated_cost": req.total_estimated_cost,
            "status": enum_value(req.status),
            "department": req.department,
        }
        facts = plain_facts(facts)
        result = await run_gated_operations_skill(
            skill_id="operations_procurement_audit",
            steps=[{"step": 1, "name": "Audit",
                    "prompt": f"Audit this purchase request for policy compliance and price reasonableness: {facts}"}],
            context={
                "request_id": request_id, "tenant_id": tenant_id, **facts,
                "instruction": "Output strict JSON: {compliant, price_reasonable, flags, approve_or_review}.",
            },
            tenant_id=tenant_id,
        )

        if result.get("status") == "SUCCESS_CLEAN":
            decision = extract_decision(result)
            # Advisory only — the request still moves through the governed
            # workflow transitions (/purchase-requests/{id}/transition), which
            # keep the WorkflowEvent audit trail this note does not replace.
            note_parts = []
            if decision.get("compliant") is not None:
                note_parts.append(f"Policy compliant: {'Yes' if decision.get('compliant') else 'No'}.")
            if decision.get("price_reasonable") is not None:
                note_parts.append(f"Price reasonable: {'Yes' if decision.get('price_reasonable') else 'No'}.")
            flags = decision.get("flags")
            if flags:
                flags_text = flags if isinstance(flags, str) else ", ".join(str(f) for f in flags)
                if flags_text.strip():
                    note_parts.append(f"Flags: {flags_text}.")
            verdict = decision.get("approve_or_review")
            if verdict:
                note_parts.append(f"AI recommendation: {verdict}.")
            req.ai_audit_note = " ".join(note_parts) if note_parts else None
            db.add(req)
            await db.commit()
            result = {**result, "decision": decision}

        return result
