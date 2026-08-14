"""
KAEOS Procurement Domain - Seed Script

Procurement is a first-class department that operates over the shared Operations
source-to-pay tables (ops_purchase_requests / _orders / _po_line_items /
_goods_receipts / _vendor_contracts). This seeder adds a comprehensive spread of
governance scenarios so the four source-to-pay controls have real data to show:

  - a clean PO whose goods receipt fully matches the order (3-way match passes);
  - a PO whose receipt is short-shipped (3-way match discrepancy);
  - a PO whose receipt is flagged damaged;
  - vendors, one of which carries a deliberately sanctioned-looking name so the
    OFAC screening action has a hit to surface.

Spend-authorization and segregation-of-duties are evaluated at approval time from
request context (approver limit, requester vs approver), so those gates are shown
live via POST /procurement/purchase-orders/{id}/approve rather than pre-stored.

Called at the end of the Operations seeder (the data lives in ops_ tables), and
also runnable standalone: python -m app.procurement.seed
"""
import asyncio
import uuid
from datetime import date, timedelta

from app.core.database import AsyncSessionLocal, async_engine
from app.models.domain import Base
from app.operations.models.procurement import (
    GoodsReceipt, POLineItem, ProcurementStatus, PurchaseOrder, PurchaseRequest,
)
from app.operations.models.vendors import VendorContract

TENANT = "tenant_acme"


def _id() -> str:
    return str(uuid.uuid4())


async def seed():
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as db:
        # ── Vendors (one sanctioned-looking name for the OFAC screen demo) ────
        vendors = [
            VendorContract(id=_id(), tenant_id=TENANT, vendor_name="Meridian Office Supply Co",
                           service_provided="Office furniture and consumables",
                           contract_value=120000.00, renewal_date=date.today() + timedelta(days=210)),
            VendorContract(id=_id(), tenant_id=TENANT, vendor_name="Northwind Logistics Inc",
                           service_provided="Freight and last-mile delivery",
                           contract_value=340000.00, renewal_date=date.today() + timedelta(days=95)),
            VendorContract(id=_id(), tenant_id=TENANT, vendor_name="BrightPath Cloud Systems",
                           service_provided="Managed cloud and backup",
                           contract_value=210000.00, renewal_date=date.today() + timedelta(days=150)),
            # Deliberately sanctioned-looking name so OFAC screening returns a hit.
            VendorContract(id=_id(), tenant_id=TENANT, vendor_name="Crimson Star Trading Ltd",
                           service_provided="Industrial equipment import",
                           contract_value=88000.00, renewal_date=date.today() + timedelta(days=60)),
        ]
        db.add_all(vendors)

        # ── Requisitions across states / departments / requesters ────────────
        reqs = [
            PurchaseRequest(id=_id(), tenant_id=TENANT, item_description="25x ergonomic workstation chairs",
                            quantity=25, unit_price=289.00, total_estimated_cost=7225.00,
                            status=ProcurementStatus.APPROVED, requested_by="Facilities Clerk", department="Workplace"),
            PurchaseRequest(id=_id(), tenant_id=TENANT, item_description="Annual managed-cloud renewal",
                            quantity=1, unit_price=210000.00, total_estimated_cost=210000.00,
                            status=ProcurementStatus.PENDING_APPROVAL, requested_by="Platform Lead", department="Engineering"),
            PurchaseRequest(id=_id(), tenant_id=TENANT, item_description="40x standing-desk converters",
                            quantity=40, unit_price=145.00, total_estimated_cost=5800.00,
                            status=ProcurementStatus.APPROVED, requested_by="Office Manager", department="Workplace"),
            PurchaseRequest(id=_id(), tenant_id=TENANT, item_description="Q3 freight contract top-up",
                            quantity=1, unit_price=48000.00, total_estimated_cost=48000.00,
                            status=ProcurementStatus.ORDERED, requested_by="Ops Coordinator", department="Operations"),
            PurchaseRequest(id=_id(), tenant_id=TENANT, item_description="Industrial press (import)",
                            quantity=1, unit_price=88000.00, total_estimated_cost=88000.00,
                            status=ProcurementStatus.DRAFT, requested_by="Plant Manager", department="Manufacturing"),
        ]
        db.add_all(reqs)
        await db.flush()

        # ── POs + line items, then receipts spanning match / short / damaged ──
        # PO 1: clean, receipt fully matches (3-way match passes).
        po1 = PurchaseOrder(id=_id(), tenant_id=TENANT, purchase_request_id=reqs[0].id,
                            po_number="PO-2026-1001", vendor_name="Meridian Office Supply Co",
                            total_amount=7225.00, status=ProcurementStatus.RECEIVED)
        # PO 2: short shipment (receipt qty < ordered -> 3-way match discrepancy).
        po2 = PurchaseOrder(id=_id(), tenant_id=TENANT, purchase_request_id=reqs[2].id,
                            po_number="PO-2026-1002", vendor_name="Meridian Office Supply Co",
                            total_amount=5800.00, status=ProcurementStatus.RECEIVED)
        # PO 3: freight, received but flagged damaged.
        po3 = PurchaseOrder(id=_id(), tenant_id=TENANT, purchase_request_id=reqs[3].id,
                            po_number="PO-2026-1003", vendor_name="Northwind Logistics Inc",
                            total_amount=48000.00, status=ProcurementStatus.RECEIVED)
        # PO 4: ordered, not yet received (open on the receiving desk).
        po4 = PurchaseOrder(id=_id(), tenant_id=TENANT, purchase_request_id=reqs[1].id,
                            po_number="PO-2026-1004", vendor_name="BrightPath Cloud Systems",
                            total_amount=210000.00, status=ProcurementStatus.ORDERED)
        db.add_all([po1, po2, po3, po4])
        await db.flush()

        lines = [
            POLineItem(id=_id(), tenant_id=TENANT, purchase_order_id=po1.id, line_number=1,
                       description="ergonomic workstation chairs", quantity=25, unit_price=289.00, amount=7225.00),
            POLineItem(id=_id(), tenant_id=TENANT, purchase_order_id=po2.id, line_number=1,
                       description="standing-desk converters", quantity=40, unit_price=145.00, amount=5800.00),
            POLineItem(id=_id(), tenant_id=TENANT, purchase_order_id=po3.id, line_number=1,
                       description="freight contract top-up", quantity=1, unit_price=48000.00, amount=48000.00),
            POLineItem(id=_id(), tenant_id=TENANT, purchase_order_id=po4.id, line_number=1,
                       description="managed-cloud annual renewal", quantity=1, unit_price=210000.00, amount=210000.00),
        ]
        db.add_all(lines)
        await db.flush()

        receipts = [
            # Full match.
            GoodsReceipt(id=_id(), tenant_id=TENANT, purchase_order_id=po1.id, po_line_item_id=lines[0].id,
                         receiver_name="Receiving Dock A", received_quantity=25, is_damaged=False, status="SUCCESS"),
            # Short shipment: 34 of 40 received -> discrepancy.
            GoodsReceipt(id=_id(), tenant_id=TENANT, purchase_order_id=po2.id, po_line_item_id=lines[1].id,
                         receiver_name="Receiving Dock A", received_quantity=34, is_damaged=False, status="PARTIAL"),
            # Damaged on arrival.
            GoodsReceipt(id=_id(), tenant_id=TENANT, purchase_order_id=po3.id, po_line_item_id=lines[2].id,
                         receiver_name="Receiving Dock B", received_quantity=1, is_damaged=True, status="DAMAGED"),
        ]
        db.add_all(receipts)

        await db.commit()
        print("[SUCCESS] Seeded Procurement database:")
        print(f"   - {len(vendors)} vendors (1 sanctions-flag demo), {len(reqs)} requisitions, "
              f"{len([po1, po2, po3, po4])} purchase orders, {len(receipts)} goods receipts "
              f"(1 match, 1 short, 1 damaged)")


if __name__ == "__main__":
    asyncio.run(seed())
