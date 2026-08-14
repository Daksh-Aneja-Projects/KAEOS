"""Deterministic three-way match: PO / receipt / invoice reconciliation.

No LLM, Decimal money. The status these tests assert is what the payment gate
and the AP badge trust, so a float slip or an inverted comparison must fail here.
"""
import uuid
from datetime import date, timedelta

from app.finance.models.accounts_payable import Invoice, InvoiceStatus
from app.finance.services.three_way_match import evaluate_three_way_match
from app.operations.models.procurement import (
    GoodsReceipt,
    POLineItem,
    ProcurementStatus,
    PurchaseOrder,
)


def _t():
    return f"tenant_twm_{uuid.uuid4().hex[:6]}"


async def _chain(db, tenant, *, po_qty=10, po_price="3545.00",
                 recv_qty=10, has_receipt=True,
                 inv_qty=10, inv_price="3545.00", link_po=True):
    po = PurchaseOrder(id=str(uuid.uuid4()), tenant_id=tenant,
                       po_number=f"PO-{uuid.uuid4().hex[:6]}",
                       vendor_name="AWS", total_amount=float(po_price) * po_qty,
                       status=ProcurementStatus.RECEIVED)
    db.add(po)
    await db.flush()
    line = POLineItem(id=str(uuid.uuid4()), tenant_id=tenant,
                      purchase_order_id=po.id, line_number=1,
                      description="compute", quantity=po_qty,
                      unit_price=po_price, amount=float(po_price) * po_qty)
    db.add(line)
    await db.flush()
    if has_receipt:
        db.add(GoodsReceipt(id=str(uuid.uuid4()), tenant_id=tenant,
                            purchase_order_id=po.id, po_line_item_id=line.id,
                            receiver_name="rcv", received_quantity=recv_qty))
        await db.flush()
    inv = Invoice(
        id=str(uuid.uuid4()), tenant_id=tenant, vendor_id=str(uuid.uuid4()),
        invoice_number=f"INV-{uuid.uuid4().hex[:6]}", status=InvoiceStatus.PENDING_APPROVAL,
        subtotal=float(inv_price) * inv_qty, total_amount=float(inv_price) * inv_qty,
        balance_due=float(inv_price) * inv_qty,
        invoice_date=date.today(), due_date=date.today() + timedelta(days=30),
        purchase_order_id=po.id if link_po else None,
        line_items=[{"qty": inv_qty, "unit_price": float(inv_price),
                     "po_line_item_id": line.id}],
    )
    db.add(inv)
    await db.commit()
    return inv


async def test_exact_match(db):
    tenant = _t()
    inv = await _chain(db, tenant)
    res = await evaluate_three_way_match(db, tenant, inv)
    assert res["status"] == "MATCHED"
    assert res["po_matched"] and res["receipt_matched"]


async def test_price_over_tolerance_is_exception(db):
    tenant = _t()
    # 10% over PO price -> way past the 2% / $1 band.
    inv = await _chain(db, tenant, inv_price="3899.50")
    res = await evaluate_three_way_match(db, tenant, inv)
    assert res["status"] == "EXCEPTION"
    assert any("overcharge" in r.lower() for r in res["reasons"])


async def test_qty_over_received_is_exception(db):
    tenant = _t()
    # Received 8 but the invoice bills 10.
    inv = await _chain(db, tenant, recv_qty=8, inv_qty=10)
    res = await evaluate_three_way_match(db, tenant, inv)
    assert res["status"] == "EXCEPTION"
    assert any("received" in r.lower() for r in res["reasons"])


async def test_po_no_receipt_is_pending(db):
    tenant = _t()
    inv = await _chain(db, tenant, has_receipt=False)
    res = await evaluate_three_way_match(db, tenant, inv)
    assert res["status"] == "PENDING_RECEIPT"
    assert res["po_matched"] and not res["receipt_matched"]


async def test_no_po_is_no_po(db):
    tenant = _t()
    inv = await _chain(db, tenant, link_po=False)
    res = await evaluate_three_way_match(db, tenant, inv)
    assert res["status"] == "NO_PO"


async def test_price_within_tolerance_matches(db):
    tenant = _t()
    # $3545 * 1.5% = $53.17 over -> within max($1, 2% = $70.90). Still MATCHED.
    inv = await _chain(db, tenant, inv_price="3598.00")
    res = await evaluate_three_way_match(db, tenant, inv)
    assert res["status"] == "MATCHED"
