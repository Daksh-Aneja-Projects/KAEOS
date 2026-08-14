"""KAEOS Procurement - gated skill runner + procurement agents.

Routes procurement agent actions through the full 7-gate ``AgentExecutor``
pipeline (Compliance -> Fairness -> Confidence/HITL -> Debate -> Execute ->
Audit) with the four procurement control tags attached, so the compliance gate
evaluates every action against THREE_WAY_MATCH / SEGREGATION_OF_DUTIES /
SPEND_AUTHORIZATION / OFAC_SANCTIONS.

The two agents follow the KAEOS convention: deterministic control work FIRST
(reusing the pure checkers + the source-to-pay service), then a gated LLM
rationale. The hard block lives in the service; the agent produces the
plain-English "why". They do NOT mutate PO state.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.runtime import AgentExecutor
from app.models.domain import Skill
from app.operations.models.procurement import PurchaseOrder, PurchaseRequest
from app.services.compliance import ComplianceEngine
from app.services.hitl_manager import hitl_manager
from app.services.json_utils import plain_facts

logger = logging.getLogger(__name__)

PROCUREMENT_COMPLIANCE = [
    "THREE_WAY_MATCH", "SEGREGATION_OF_DUTIES",
    "SPEND_AUTHORIZATION", "OFAC_SANCTIONS",
]


async def run_gated_procurement_skill(
    skill_id: str,
    steps: List[Dict[str, Any]],
    context: Dict[str, Any],
    tenant_id: str,
    *,
    compliance_tags: Optional[List[str]] = None,
    confidence: float = 0.85,
    domain: str = "procurement",
) -> Dict[str, Any]:
    """Run a procurement skill through the gated ``AgentExecutor`` and return its
    result dict (status is one of PENDING_HITL / BLOCKED_* / SUCCESS_CLEAN)."""
    compliance_tags = compliance_tags or list(PROCUREMENT_COMPLIANCE)
    execution_id = context.get("execution_id") or str(uuid.uuid4())

    skill_dict = {
        "skill_id": skill_id,
        "department": domain,
        "steps": steps,
        "compliance_tags": compliance_tags,
        "confidence": confidence,
    }
    skill_obj = Skill(
        skill_id=skill_id, department=domain, domain=domain,
        compliance_tags=compliance_tags, confidence=confidence,
        confidence_tier="INFERRED", execution_count=0, success_rate=0.0,
        steps=steps,
    )
    ctx = {
        **context,
        "tenant_id": tenant_id,
        "execution_id": execution_id,
        "_skill_obj": skill_obj,
    }
    executor = AgentExecutor(ComplianceEngine(), hitl_manager)
    return await executor.execute_skill(skill_dict, ctx)


def extract_decision(result: Dict[str, Any]) -> Dict[str, Any]:
    """Best-effort parse of the primary step's JSON decision from a gated result."""
    from app.services.json_utils import extract_json_object

    chain = result.get("reasoning_chain") or []
    if not chain:
        return {}
    decision_text = chain[-1].get("decision", "") or ""
    try:
        return extract_json_object(decision_text)
    except ValueError as e:
        logger.warning("extract_decision: could not parse JSON decision: %s", e)
        return {}


async def sourcing_agent(db: AsyncSession, request_id: str, tenant_id: str) -> Dict[str, Any]:
    """Assess a purchase requisition for policy fit and price reasonableness,
    routed through the procurement gate pipeline. Grounds on the real row."""
    req = (await db.execute(select(PurchaseRequest).where(
        PurchaseRequest.id == request_id, PurchaseRequest.tenant_id == tenant_id
    ))).scalar_one_or_none()
    if req is None:
        raise ValueError(f"Purchase request {request_id} not found")

    facts = plain_facts({
        "item_description": (req.item_description or "")[:800],
        "quantity": req.quantity,
        "unit_price": req.unit_price,
        "total_estimated_cost": req.total_estimated_cost,
        "status": getattr(req.status, "value", req.status),
        "department": req.department,
    })
    return await run_gated_procurement_skill(
        skill_id="procurement_sourcing_assess",
        steps=[{"step": 1, "name": "Source",
                "prompt": f"Assess this purchase requisition for policy fit and price "
                          f"reasonableness before a PO is raised: {facts}"}],
        context={"request_id": request_id, "tenant_id": tenant_id, **facts,
                 "instruction": "Output strict JSON: {compliant, price_reasonable, "
                                "recommend_po, flags}."},
        tenant_id=tenant_id,
    )


async def spend_guard_agent(
    db: AsyncSession, po_id: str, tenant_id: str, *,
    approver: str, approver_limit: Optional[Any] = None,
    sanctions_list: Optional[list] = None,
) -> Dict[str, Any]:
    """Deterministic control evaluation of a PO (spend-auth + SoD + 3-way match +
    OFAC via the source-to-pay service) followed by a gated plain-English
    rationale. Read-only: it advises, it does not approve."""
    from app.procurement.services.source_to_pay import (
        ProcurementNotFound, evaluate_po_gates,
    )

    po = (await db.execute(select(PurchaseOrder).where(
        PurchaseOrder.id == po_id, PurchaseOrder.tenant_id == tenant_id
    ))).scalar_one_or_none()
    if po is None:
        raise ProcurementNotFound(f"Purchase order {po_id} not found")

    gates = await evaluate_po_gates(
        db, tenant_id, po, approver=approver, approver_limit=approver_limit,
        sanctions_list=sanctions_list)
    blocked = [g for g in gates if g["blocking"]]

    facts = plain_facts({
        "po_number": po.po_number, "vendor": po.vendor_name,
        "total_amount": po.total_amount,
        "gate_summary": [{"control": g["code"], "status": g["status"]} for g in gates],
    })
    gated = await run_gated_procurement_skill(
        skill_id="procurement_spend_guard",
        steps=[{"step": 1, "name": "Guard",
                "prompt": f"Explain, for an approver, whether this purchase order is "
                          f"safe to approve given its control outcomes: {facts}"}],
        context={"po_id": po_id, "tenant_id": tenant_id, **facts,
                 "instruction": "Output strict JSON: {safe_to_approve, blocking_controls, "
                                "recommendation}."},
        tenant_id=tenant_id,
    )
    return {"po_id": po_id, "gates": gates,
            "blocking_controls": [g["code"] for g in blocked],
            "safe_to_approve": not blocked, "gated": gated}
