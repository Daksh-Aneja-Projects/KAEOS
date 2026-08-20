"""KAEOS Procurement Domain - V1 API Router.

First-class /procurement surface. Owns no tables: it reads and writes the
Operations ``ops_*`` procurement tables and runs the source-to-pay controls.
Reads take Depends(get_tenant_id); writes take require_role("operator");
the approver is always the authenticated principal, never a client field.
"""
from __future__ import annotations

import logging
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func as sqlfunc
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import record_security_event
from app.core.department_endpoints import get_or_404, make_department_workflow_router
from app.core.database import get_db
from app.core.tenant import approver_identity, get_tenant_id, require_role
from app.operations.models.procurement import (
    GoodsReceipt,
    POLineItem,
    ProcurementStatus,
    PurchaseOrder,
    PurchaseRequest,
)
from app.operations.models.vendors import VendorContract, VendorPerformance
from app.procurement.agents.gated_runner import (
    extract_decision,
    sourcing_agent,
    spend_guard_agent,
)
from app.procurement.services.source_to_pay import (
    ProcurementBlocked,
    ProcurementNotFound,
    approve_purchase_order,
    run_three_way_match,
    screen_vendor,
)
from app.models.execution_status import ExecutionStatus

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/procurement", tags=["Procurement"])


# ── Dashboard ────────────────────────────────────────────────────────────
@router.get("/dashboard")
async def procurement_dashboard(
    tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)
):
    """Source-to-pay KPIs across requisitions, POs, and receipts."""
    async def _count(model, *where):
        q = select(sqlfunc.count()).select_from(model).where(model.tenant_id == tenant_id, *where)
        return int((await db.execute(q)).scalar() or 0)

    open_po = await _count(PurchaseOrder, PurchaseOrder.status.in_(
        [ProcurementStatus.PENDING_APPROVAL, ProcurementStatus.APPROVED, ProcurementStatus.ORDERED]))
    committed = float((await db.execute(
        select(sqlfunc.coalesce(sqlfunc.sum(PurchaseOrder.total_amount), 0))
        .where(PurchaseOrder.tenant_id == tenant_id,
               PurchaseOrder.status.in_([ProcurementStatus.APPROVED, ProcurementStatus.ORDERED]))
    )).scalar() or 0)
    return {
        "open_requisitions": await _count(
            PurchaseRequest, PurchaseRequest.status.in_(
                [ProcurementStatus.DRAFT, ProcurementStatus.PENDING_APPROVAL])),
        "purchase_orders_open": open_po,
        "pending_approval": await _count(
            PurchaseOrder, PurchaseOrder.status == ProcurementStatus.PENDING_APPROVAL),
        "goods_receipts": await _count(GoodsReceipt),
        "committed_spend": committed,
    }


# ── Requisitions ─────────────────────────────────────────────────────────
class RequisitionCreate(BaseModel):
    item_description: str = Field(..., min_length=1, max_length=256)
    quantity: int = Field(1, ge=1)
    unit_price: float = Field(0, ge=0)
    requested_by: Optional[str] = Field(None, max_length=128)
    department: Optional[str] = Field(None, max_length=64)


@router.get("/requisitions")
async def list_requisitions(
    tenant_id: str = Depends(get_tenant_id), status: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    q = select(PurchaseRequest).where(PurchaseRequest.tenant_id == tenant_id)
    if status:
        q = q.where(PurchaseRequest.status == status)
    rows = (await db.execute(q.order_by(PurchaseRequest.created_at.desc()).limit(200))).scalars().all()
    return [{"id": r.id, "item": r.item_description, "quantity": r.quantity,
             "unit_price": float(r.unit_price or 0),
             "estimated_cost": float(r.total_estimated_cost or 0),
             "status": r.status.value if hasattr(r.status, "value") else str(r.status),
             "requested_by": r.requested_by, "department": r.department} for r in rows]


@router.post("/requisitions", status_code=201)
async def create_requisition(
    body: RequisitionCreate,
    tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db),
):
    tenant_id = tenant["tenant_id"]
    est = round(body.quantity * body.unit_price, 2)
    req = PurchaseRequest(
        tenant_id=tenant_id, item_description=body.item_description,
        quantity=body.quantity, unit_price=body.unit_price,
        total_estimated_cost=est,
        requested_by=body.requested_by or approver_identity(tenant),
        department=body.department,
    )
    db.add(req)
    await db.commit()
    await db.refresh(req)
    return {"id": req.id, "item": req.item_description, "estimated_cost": float(req.total_estimated_cost or 0),
            "status": req.status.value if hasattr(req.status, "value") else str(req.status)}


# Procurement's gated agent endpoints now match the shared contract: ValueError
# -> 404 with detail=, and a logged, detail-free 500 for anything else (S4.5).
@router.post("/requisitions/{request_id}/assess")
async def assess_requisition(
    request_id: str,
    tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db),
):
    """Route a requisition through the gated Sourcing Agent (policy fit and
    price reasonableness) for a plain-English recommendation before a PO is
    raised. Advisory only - it never writes to the requisition."""
    tenant_id = tenant["tenant_id"]
    try:
        result = await sourcing_agent(db, request_id, tenant_id)
    except ValueError as e:
        raise HTTPException(404, detail=str(e)) from e
    except HTTPException:
        raise  # a deliberate status (e.g. 409 invalid transition) is not a 500
    except Exception as e:
        logger.exception("%s failed", __name__)
        raise HTTPException(500, detail="Internal error - see server logs") from e
    await record_security_event(
        tenant_id=tenant_id, event_type="MODIFICATION", action="EXECUTE",
        actor=approver_identity(tenant), actor_role=tenant.get("role"),
        resource_type="purchase_request", resource_id=request_id,
        details={"status": result.get("status")},
    )
    if result.get("status") == ExecutionStatus.SUCCESS_CLEAN:
        result["assessment"] = extract_decision(result)
    return result


# ── Purchase orders ──────────────────────────────────────────────────────
class POLineIn(BaseModel):
    description: Optional[str] = Field(None, max_length=256)
    quantity: int = Field(1, ge=1)
    unit_price: float = Field(0, ge=0)


class POCreate(BaseModel):
    vendor_name: str = Field(..., min_length=1, max_length=256)
    po_number: Optional[str] = Field(None, max_length=32)
    purchase_request_id: Optional[str] = None
    vendor_id: Optional[str] = None
    lines: list[POLineIn] = Field(default_factory=list)


class POApproveIn(BaseModel):
    approver_limit: Optional[float] = None
    sanctions_list: Optional[list] = None
    requester: Optional[str] = None
    receiver: Optional[str] = None


@router.get("/purchase-orders")
async def list_purchase_orders(
    tenant_id: str = Depends(get_tenant_id), status: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    q = select(PurchaseOrder).where(PurchaseOrder.tenant_id == tenant_id)
    if status:
        q = q.where(PurchaseOrder.status == status)
    rows = (await db.execute(q.order_by(PurchaseOrder.created_at.desc()).limit(200))).scalars().all()
    return [{"id": p.id, "po_number": p.po_number, "vendor": p.vendor_name,
             "vendor_id": p.vendor_id, "total": float(p.total_amount or 0),
             "status": p.status.value if hasattr(p.status, "value") else str(p.status)} for p in rows]


@router.post("/purchase-orders", status_code=201)
async def create_purchase_order(
    body: POCreate,
    tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db),
):
    tenant_id = tenant["tenant_id"]
    total = round(sum(l.quantity * l.unit_price for l in body.lines), 2)
    po = PurchaseOrder(
        tenant_id=tenant_id,
        po_number=body.po_number or f"PO-{uuid.uuid4().hex[:8].upper()}",
        vendor_name=body.vendor_name, vendor_id=body.vendor_id,
        purchase_request_id=body.purchase_request_id, total_amount=total,
        status=ProcurementStatus.PENDING_APPROVAL,
    )
    db.add(po)
    await db.flush()
    for i, l in enumerate(body.lines, start=1):
        db.add(POLineItem(tenant_id=tenant_id, purchase_order_id=po.id, line_number=i,
                          description=l.description, quantity=l.quantity,
                          unit_price=l.unit_price, amount=round(l.quantity * l.unit_price, 2)))
    await db.commit()
    await db.refresh(po)
    await record_security_event(
        tenant_id=tenant_id, event_type="MODIFICATION", action="WRITE",
        actor=approver_identity(tenant), actor_role=tenant.get("role"),
        resource_type="purchase_order", resource_id=po.id,
        details={"po_number": po.po_number, "total": float(po.total_amount or 0)},
    )
    return {"id": po.id, "po_number": po.po_number, "total": float(po.total_amount or 0),
            "status": po.status.value}


@router.post("/purchase-orders/{po_id}/approve")
async def approve_po(
    po_id: str, body: POApproveIn,
    tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db),
):
    """Approve a PO through the four-control gate chain (spend-auth + SoD +
    three-way match + OFAC). Fail-closed: a blocking control returns 409 and the
    PO is not approved. The approver is the authenticated principal."""
    tenant_id = tenant["tenant_id"]
    try:
        result = await approve_purchase_order(
            db, tenant_id, po_id,
            approver=approver_identity(tenant),
            approver_limit=body.approver_limit,
            sanctions_list=body.sanctions_list,
            requester=body.requester, receiver=body.receiver,
        )
    except ProcurementNotFound as e:
        raise HTTPException(404, str(e))
    except ProcurementBlocked as e:
        raise HTTPException(409, detail={"message": str(e), "gates": e.gates})
    await record_security_event(
        tenant_id=tenant_id, event_type="MODIFICATION", action="APPROVE",
        actor=approver_identity(tenant), actor_role=tenant.get("role"),
        resource_type="purchase_order", resource_id=po_id,
        details={"status": result["status"]},
    )
    return result


@router.post("/purchase-orders/{po_id}/guard")
async def guard_purchase_order(
    po_id: str, body: POApproveIn,
    tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db),
):
    """Spend Guard Agent: evaluates the same four control gates the approval
    endpoint enforces, then a gated LLM explains for an approver whether the
    order looks safe to approve. Read-only - it never approves or blocks the
    PO; it advises. Meant to be surfaced alongside the approval panel."""
    tenant_id = tenant["tenant_id"]
    try:
        result = await spend_guard_agent(
            db, po_id, tenant_id, approver=approver_identity(tenant),
            approver_limit=body.approver_limit, sanctions_list=body.sanctions_list,
        )
    except ProcurementNotFound as e:
        raise HTTPException(404, str(e))
    await record_security_event(
        tenant_id=tenant_id, event_type="MODIFICATION", action="EXECUTE",
        actor=approver_identity(tenant), actor_role=tenant.get("role"),
        resource_type="purchase_order", resource_id=po_id,
        details={"safe_to_approve": result.get("safe_to_approve")},
    )
    gated = result.get("gated") or {}
    if gated.get("status") == ExecutionStatus.SUCCESS_CLEAN:
        result["rationale"] = extract_decision(gated)
    return result


# ── Goods receipts ───────────────────────────────────────────────────────
class GoodsReceiptCreate(BaseModel):
    purchase_order_id: str
    receiver_name: str = Field(..., min_length=1, max_length=128)
    received_quantity: int = Field(1, ge=0)
    po_line_item_id: Optional[str] = None
    is_damaged: bool = False


@router.get("/goods-receipts")
async def list_goods_receipts(
    tenant_id: str = Depends(get_tenant_id), po_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    q = select(GoodsReceipt).where(GoodsReceipt.tenant_id == tenant_id)
    if po_id:
        q = q.where(GoodsReceipt.purchase_order_id == po_id)
    rows = (await db.execute(q.order_by(GoodsReceipt.created_at.desc()).limit(200))).scalars().all()
    return [{"id": r.id, "purchase_order_id": r.purchase_order_id, "receiver": r.receiver_name,
             "received_quantity": r.received_quantity, "is_damaged": r.is_damaged,
             "status": r.status} for r in rows]


@router.post("/goods-receipts", status_code=201)
async def create_goods_receipt(
    body: GoodsReceiptCreate,
    tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db),
):
    tenant_id = tenant["tenant_id"]
    await get_or_404(db, PurchaseOrder, body.purchase_order_id, tenant_id, detail="Purchase order not found")
    gr = GoodsReceipt(
        tenant_id=tenant_id, purchase_order_id=body.purchase_order_id,
        po_line_item_id=body.po_line_item_id, receiver_name=body.receiver_name,
        received_quantity=body.received_quantity, is_damaged=body.is_damaged,
    )
    db.add(gr)
    await db.commit()
    await db.refresh(gr)
    return {"id": gr.id, "purchase_order_id": gr.purchase_order_id,
            "receiver": gr.receiver_name, "received_quantity": gr.received_quantity}


# ── Three-way match ──────────────────────────────────────────────────────
@router.get("/three-way-match/{po_id}")
async def three_way_match(
    po_id: str, tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)
):
    """Reconcile every invoice linked to this PO against PO lines + goods
    receipts (Finance three-way match)."""
    try:
        return await run_three_way_match(db, tenant_id, po_id)
    except ProcurementNotFound as e:
        raise HTTPException(404, str(e))


# ── Vendors ──────────────────────────────────────────────────────────────
class VendorScreenIn(BaseModel):
    vendor_name: str = Field(..., min_length=1, max_length=256)
    sanctions_list: Optional[list] = None


@router.get("/vendors")
async def list_procurement_vendors(
    tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)
):
    """Every vendor under contract (app.operations.models.vendors.VendorContract),
    left-joined to its latest performance sheet, with PO count and committed
    spend rolled up by vendor name. A vendor with no purchase order yet still
    appears here - onboarding and sanctions screening happen before the first
    PO is ever raised, not after."""
    latest_perf_id = (
        select(VendorPerformance.id)
        .where(VendorPerformance.vendor_contract_id == VendorContract.id)
        .order_by(VendorPerformance.created_at.desc())
        .limit(1)
        .correlate(VendorContract)
        .scalar_subquery()
    )
    po_agg = (
        select(PurchaseOrder.vendor_name.label("vendor_name"),
               sqlfunc.count().label("po_count"),
               sqlfunc.coalesce(sqlfunc.sum(PurchaseOrder.total_amount), 0).label("committed_spend"))
        .where(PurchaseOrder.tenant_id == tenant_id)
        .group_by(PurchaseOrder.vendor_name)
        .subquery()
    )
    rows = (await db.execute(
        select(VendorContract, VendorPerformance.overall_performance_score,
               po_agg.c.po_count, po_agg.c.committed_spend)
        .outerjoin(VendorPerformance, VendorPerformance.id == latest_perf_id)
        .outerjoin(po_agg, po_agg.c.vendor_name == VendorContract.vendor_name)
        .where(VendorContract.tenant_id == tenant_id)
        .order_by(VendorContract.vendor_name)
        .limit(200)
    )).all()
    return [{
        "vendor": c.vendor_name,
        "vendor_id": c.vendor_id,
        "service_provided": c.service_provided,
        "contract_value": float(c.contract_value or 0),
        "renewal_date": c.renewal_date.isoformat() if c.renewal_date else None,
        "performance_score": float(perf) if perf is not None else None,
        "po_count": int(cnt or 0),
        "committed_spend": float(spend or 0),
    } for c, perf, cnt, spend in rows]


@router.post("/vendors/screen")
async def screen_procurement_vendor(
    body: VendorScreenIn,
    tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db),
):
    """OFAC / denied-parties screen for a vendor. A hit returns blocking=True."""
    return await screen_vendor(body.vendor_name, body.sanctions_list)


# ═══════════════════════════════════════════════════════════════════════
# Analytics & Workflow Layer (shared engine: app.core.workflow)
# ═══════════════════════════════════════════════════════════════════════
from app.core.workflow import (  # noqa: E402
    TransitionRequest, apply_transition,
)
from app.procurement.services.analytics import procurement_analytics  # noqa: E402
from app.procurement.services.workflows import SPECS as WORKFLOW_SPECS  # noqa: E402


@router.get("/analytics")
async def get_procurement_analytics(
    tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)
):
    """Spend, vendor-risk, cycle-time and PO-funnel KPIs computed live from
    tenant rows."""
    return await procurement_analytics(db, tenant_id, charts=True)


# Generated from the shared factory in app/core/department_endpoints.py.
# Endpoint names and docstrings are the hand-written originals, so the
# operationIds and descriptions in the OpenAPI schema are unchanged.
router.include_router(make_department_workflow_router(
    "procurement", WORKFLOW_SPECS,
    workflows_doc='Declared state machines - the frontend can render lifecycle actions from\n    this. PO approval itself stays off this map; see services/workflows.py.',
    events_doc='Tenant-scoped transition audit trail for procurement entities.',
))


@router.post("/requisitions/{request_id}/transition")
async def transition_requisition(
    request_id: str, body: TransitionRequest,
    tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db),
):
    """Move a requisition through draft, approval, ordered, received."""
    return await apply_transition(db, WORKFLOW_SPECS["procurement_requisition"],
                                  request_id, body.to_state, tenant, note=body.note)


@router.post("/purchase-orders/{po_id}/transition")
async def transition_purchase_order(
    po_id: str, body: TransitionRequest,
    tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db),
):
    """Move an already-approved PO through ordered / received, or cancel a
    draft or pending one. Does not accept PENDING_APPROVAL -> APPROVED: use
    POST /purchase-orders/{id}/approve, which is fail-closed on the four
    source-to-pay controls."""
    return await apply_transition(db, WORKFLOW_SPECS["procurement_purchase_order"],
                                  po_id, body.to_state, tenant, note=body.note)


router.include_router(make_department_workflow_router(
    "procurement", WORKFLOW_SPECS,
    bulk_doc='Apply one transition to up to 200 procurement entities; per-id outcomes.',
))
