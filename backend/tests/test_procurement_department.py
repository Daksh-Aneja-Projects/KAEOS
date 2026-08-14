"""Procurement department: source-to-pay control gates.

Deterministic (no LLM). A PO is approved only when spend-auth, segregation of
duties, three-way match, and OFAC all pass; any failing control blocks approval
fail-closed and leaves the PO PENDING_APPROVAL.
"""
import uuid
from datetime import date, timedelta

import pytest

from app.finance.models.accounts_payable import Invoice, InvoiceStatus
from app.operations.models.procurement import (
    GoodsReceipt,
    POLineItem,
    ProcurementStatus,
    PurchaseOrder,
)
from app.procurement.services.source_to_pay import (
    ProcurementBlocked,
    approve_purchase_order,
    screen_vendor,
)

CLEAN_LIST = ["Sanctioned Enemy LLC"]  # non-empty so OFAC can actually screen


def _t():
    return f"tenant_proc_{uuid.uuid4().hex[:6]}"


async def _po(db, tenant, *, vendor="AWS", qty=10, price="100.00", total=None):
    po = PurchaseOrder(id=str(uuid.uuid4()), tenant_id=tenant,
                       po_number=f"PO-{uuid.uuid4().hex[:6]}", vendor_name=vendor,
                       total_amount=total if total is not None else float(price) * qty,
                       status=ProcurementStatus.PENDING_APPROVAL)
    db.add(po)
    await db.flush()
    line = POLineItem(id=str(uuid.uuid4()), tenant_id=tenant, purchase_order_id=po.id,
                      line_number=1, description="widgets", quantity=qty,
                      unit_price=price, amount=float(price) * qty)
    db.add(line)
    db.add(GoodsReceipt(id=str(uuid.uuid4()), tenant_id=tenant, purchase_order_id=po.id,
                        po_line_item_id=line.id, receiver_name="receiver-bob",
                        received_quantity=qty))
    await db.commit()
    return po, line


async def _link_invoice(db, tenant, po, line, *, inv_qty, inv_price):
    inv = Invoice(id=str(uuid.uuid4()), tenant_id=tenant, vendor_id=str(uuid.uuid4()),
                  invoice_number=f"INV-{uuid.uuid4().hex[:6]}", status=InvoiceStatus.PENDING_APPROVAL,
                  subtotal=inv_price * inv_qty, total_amount=inv_price * inv_qty,
                  balance_due=inv_price * inv_qty, invoice_date=date.today(),
                  due_date=date.today() + timedelta(days=30), purchase_order_id=po.id,
                  line_items=[{"qty": inv_qty, "unit_price": inv_price, "po_line_item_id": line.id}])
    db.add(inv)
    await db.commit()
    return inv


async def test_clean_po_is_approved(db):
    tenant = _t()
    po, _ = await _po(db, tenant, price="100.00", qty=10)  # total 1000
    result = await approve_purchase_order(
        db, tenant, po.id, approver="carol", approver_limit=5000,
        sanctions_list=CLEAN_LIST, requester="alice", receiver="receiver-bob")
    assert result["status"] == ProcurementStatus.APPROVED.value
    await db.refresh(po)
    assert po.status == ProcurementStatus.APPROVED


async def test_spend_authorization_blocks(db):
    tenant = _t()
    po, _ = await _po(db, tenant, price="1000.00", qty=10)  # total 10000
    with pytest.raises(ProcurementBlocked) as ei:
        await approve_purchase_order(
            db, tenant, po.id, approver="carol", approver_limit=5000,
            sanctions_list=CLEAN_LIST, requester="alice", receiver="receiver-bob")
    assert any(g["code"] == "SPEND_AUTHORIZATION" and g["blocking"] for g in ei.value.gates)
    await db.refresh(po)
    assert po.status == ProcurementStatus.PENDING_APPROVAL  # not approved


async def test_segregation_of_duties_blocks(db):
    tenant = _t()
    po, _ = await _po(db, tenant)
    with pytest.raises(ProcurementBlocked) as ei:
        # approver == requester -> SoD conflict
        await approve_purchase_order(
            db, tenant, po.id, approver="alice", approver_limit=5000,
            sanctions_list=CLEAN_LIST, requester="alice", receiver="receiver-bob")
    assert any(g["code"] == "SEGREGATION_OF_DUTIES" and g["blocking"] for g in ei.value.gates)


async def test_three_way_match_exception_blocks(db):
    tenant = _t()
    po, line = await _po(db, tenant, price="100.00", qty=10)
    # Invoice bills 10% over PO unit price -> EXCEPTION -> blocks approval.
    await _link_invoice(db, tenant, po, line, inv_qty=10, inv_price=200.0)
    with pytest.raises(ProcurementBlocked) as ei:
        await approve_purchase_order(
            db, tenant, po.id, approver="carol", approver_limit=50000,
            sanctions_list=CLEAN_LIST, requester="alice", receiver="receiver-bob")
    assert any(g["code"] == "THREE_WAY_MATCH" and g["blocking"] for g in ei.value.gates)


async def test_ofac_hit_blocks_vendor(db):
    hit = await screen_vendor("Sanctioned Enemy LLC", CLEAN_LIST)
    assert hit["blocking"] and hit["status"] == "BLOCK"
    clean = await screen_vendor("Honest Widgets Inc", CLEAN_LIST)
    assert not clean["blocking"] and clean["status"] == "PASS"


async def test_ofac_hit_blocks_po_approval(db):
    tenant = _t()
    po, _ = await _po(db, tenant, vendor="Sanctioned Enemy LLC")
    with pytest.raises(ProcurementBlocked) as ei:
        await approve_purchase_order(
            db, tenant, po.id, approver="carol", approver_limit=50000,
            sanctions_list=CLEAN_LIST, requester="alice", receiver="receiver-bob")
    assert any(g["code"] == "OFAC_SANCTIONS" and g["blocking"] for g in ei.value.gates)
