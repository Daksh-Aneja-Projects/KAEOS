"""KAEOS Operations Domain - Procurement Audit Agent

Context-grounding: the agent loads the real entity and reasons over its
content. Passing only an opaque id left the model classifying an identifier
(confirmed ungrounded on real onboarded data), so facts are non-optional.
"""
from typing import Any, Dict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.operations.agents.gated_runner import run_gated_operations_skill
from app.operations.models.procurement import PurchaseRequest
from app.services.json_utils import plain_facts


def _v(x):
    return getattr(x, "value", x)


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
            "status": _v(req.status),
            "department": req.department,
        }
        facts = plain_facts(facts)
        return await run_gated_operations_skill(
            skill_id="operations_procurement_audit",
            steps=[{"step": 1, "name": "Audit",
                    "prompt": f"Audit this purchase request for policy compliance and price reasonableness: {facts}"}],
            context={
                "request_id": request_id, "tenant_id": tenant_id, **facts,
                "instruction": "Output strict JSON: {compliant, price_reasonable, flags, approve_or_review}.",
            },
            tenant_id=tenant_id,
        )
