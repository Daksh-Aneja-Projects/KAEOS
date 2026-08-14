"""KAEOS Finance - deterministic three-way match (PO / receipt / invoice).

No LLM, all Decimal. This is the control the AP badge advertises: it loads the
purchase order, its line items, and its goods receipts, reconciles them against
the invoice's own lines, and returns a status the payment path can gate on.

Reuses the pure deterministic checker at
``app.compliance.checkers.procurement.check_three_way_match`` (THREE_WAY_MATCH)
one line at a time so each line carries its own price tolerance:

    invoice qty  PASS if invoice_qty <= min(ordered_qty, received_qty)  (+ QTY_TOL)
    invoice price PASS if overcharge <= max(PRICE_ABS_TOL, po_price * PRICE_PCT_TOL)

Under-billing and honest partial delivery pass; only billing beyond what was
ordered or received, or an overcharge past tolerance, is an EXCEPTION.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.compliance.base import CheckStatus
from app.compliance.checkers.procurement import check_three_way_match
from app.finance.services.gl import _money
from app.operations.models.procurement import (
    GoodsReceipt,
    POLineItem,
    PurchaseOrder,
)

# ponytail: fixed tolerances; per-tenant override via ops DepartmentConfig is
# the upgrade path if buyers want their own bands.
PRICE_PCT_TOL = Decimal("0.02")   # 2% of PO unit price
PRICE_ABS_TOL = Decimal("1.00")   # or $1.00, whichever is larger
QTY_TOL = 0                       # invoice may bill at most what was received


def _result(status: str, *, po_matched: bool = False, receipt_matched: bool = False,
            lines: Optional[list] = None, reasons: Optional[list] = None,
            evidence_ids: Optional[list] = None) -> dict[str, Any]:
    return {
        "status": status,
        "po_matched": po_matched,
        "receipt_matched": receipt_matched,
        "lines": lines or [],
        "reasons": reasons or [],
        "evidence_ids": evidence_ids or [],
    }


def _find_invoice_line(inv_lines: list, po_line: POLineItem, idx: int) -> Optional[dict]:
    """Pair a PO line to the invoice line billing it: by explicit
    po_line_item_id, then line_number, then position."""
    for il in inv_lines:
        if isinstance(il, dict) and il.get("po_line_item_id") == po_line.id:
            return il
    for il in inv_lines:
        if isinstance(il, dict) and il.get("line_number") == po_line.line_number:
            return il
    if idx < len(inv_lines) and isinstance(inv_lines[idx], dict):
        return inv_lines[idx]
    return None


async def evaluate_three_way_match(
    db: AsyncSession, tenant_id: str, invoice
) -> dict[str, Any]:
    """Reconcile an invoice against its PO and goods receipts.

    Returns {status, po_matched, receipt_matched, lines, reasons, evidence_ids}
    where status is one of MATCHED, EXCEPTION, PENDING_RECEIPT, NO_PO.
    """
    po_id = getattr(invoice, "purchase_order_id", None)
    if not po_id:
        return _result("NO_PO", evidence_ids=[invoice.id], reasons=[
            "No purchase order is linked to this invoice, so a three-way match "
            "cannot be performed."])

    po = (await db.execute(select(PurchaseOrder).where(
        PurchaseOrder.id == po_id, PurchaseOrder.tenant_id == tenant_id
    ))).scalar_one_or_none()
    if po is None:
        return _result("NO_PO", evidence_ids=[invoice.id], reasons=[
            "The purchase order referenced by this invoice was not found."])

    po_lines = (await db.execute(select(POLineItem).where(
        POLineItem.purchase_order_id == po_id, POLineItem.tenant_id == tenant_id
    ).order_by(POLineItem.line_number))).scalars().all()

    receipts = (await db.execute(select(GoodsReceipt).where(
        GoodsReceipt.purchase_order_id == po_id, GoodsReceipt.tenant_id == tenant_id
    ))).scalars().all()
    receipt_ids = [r.id for r in receipts]
    evidence = [po_id, *receipt_ids, invoice.id]

    if not receipts:
        return _result("PENDING_RECEIPT", po_matched=True, evidence_ids=evidence,
                       reasons=["The purchase order is linked but no goods receipt "
                                "has been recorded yet, so delivery cannot be confirmed."])

    # Received quantity per PO line, plus header (unattributed) receipts.
    line_received: dict[str, int] = {}
    header_received = 0
    for r in receipts:
        lid = getattr(r, "po_line_item_id", None)
        if lid:
            line_received[lid] = line_received.get(lid, 0) + int(r.received_quantity or 0)
        else:
            header_received += int(r.received_quantity or 0)

    inv_lines = list(invoice.line_items or [])

    # Degenerate fallback: no PO line items -> compare invoice total vs PO total
    # as one synthetic line (qty 1). Keeps the control honest for header-only data.
    if not po_lines:
        lines = [{
            "line_number": 1, "description": "Order total",
            "po_qty": Decimal(1), "po_unit_price": _money(po.total_amount),
            "received_qty": Decimal(1 if header_received else 0),
            "invoice_qty": Decimal(1), "invoice_unit_price": _money(invoice.total_amount),
        }]
        ctx = {"three_way_match": {
            "po": {"qty": 1, "unit_price": _money(po.total_amount)},
            "receipt": {"qty": 1},
            "invoice": {"qty": 1, "unit_price": _money(invoice.total_amount)},
        }, "qty_tolerance": QTY_TOL,
            "price_tolerance": max(PRICE_ABS_TOL, _money(po.total_amount) * PRICE_PCT_TOL)}
        res = check_three_way_match(ctx)
        reasons = [f.message for f in res.findings]
        if res.status == CheckStatus.BLOCK:
            return _result("EXCEPTION", po_matched=True, lines=lines,
                           reasons=reasons, evidence_ids=evidence)
        return _result("MATCHED", po_matched=True, receipt_matched=True,
                       lines=lines, evidence_ids=evidence)

    only_header = not line_received and header_received > 0
    lines_out: list[dict] = []
    reasons: list[str] = []
    any_block = False
    any_unverifiable = False

    for idx, pol in enumerate(po_lines):
        po_qty = int(pol.quantity or 0)
        po_price = _money(pol.unit_price)
        # Per-line received: attributed receipts, or spread a single header
        # receipt onto a single-line PO.
        if pol.id in line_received:
            rcv = line_received[pol.id]
        elif only_header and len(po_lines) == 1:
            rcv = header_received
        else:
            rcv = None

        il = _find_invoice_line(inv_lines, pol, idx)
        if il is not None:
            # Decimal, not int(): a services invoice billing a fractional qty
            # (e.g. 10.9h against 10 received) must NOT truncate down into
            # tolerance - that is a fail-open on the exact control this enforces.
            try:
                inv_qty = Decimal(str(il.get("qty") if il.get("qty") is not None else po_qty))
            except (InvalidOperation, TypeError, ValueError):
                # Unparseable qty is not a pass: bill "more than ordered" so the
                # line fails closed as an EXCEPTION rather than truncating or 500-ing.
                inv_qty = Decimal(po_qty) + Decimal("1")
            inv_price = _money(il.get("unit_price") if il.get("unit_price") is not None else po_price)
        else:
            # No invoice line for this PO line: bill nothing (honest under-bill).
            inv_qty, inv_price = 0, po_price

        line_tol = max(PRICE_ABS_TOL, po_price * PRICE_PCT_TOL)
        ctx = {"three_way_match": {
            "line_id": f"line {pol.line_number}",
            "po": {"qty": po_qty, "unit_price": po_price},
            "receipt": {"qty": rcv},
            "invoice": {"qty": inv_qty, "unit_price": inv_price},
        }, "qty_tolerance": QTY_TOL, "price_tolerance": line_tol}
        res = check_three_way_match(ctx)
        line_reasons = [f.message for f in res.findings]
        reasons.extend(line_reasons)
        if res.status == CheckStatus.BLOCK:
            any_block = True
        elif res.status == CheckStatus.ADVISORY:
            any_unverifiable = True

        lines_out.append({
            "line_number": pol.line_number,
            "description": pol.description,
            "po_qty": po_qty, "po_unit_price": str(po_price),
            "received_qty": rcv,
            "invoice_qty": inv_qty, "invoice_unit_price": str(inv_price),
            "status": res.status.value,
        })

    if any_block or any_unverifiable:
        # Fail closed: a real overcharge/over-bill blocks; an unverifiable leg
        # is not a silent pass either.
        return _result("EXCEPTION", po_matched=True, lines=lines_out,
                       reasons=reasons, evidence_ids=evidence)
    return _result("MATCHED", po_matched=True, receipt_matched=True,
                   lines=lines_out, evidence_ids=evidence)


def match_summary(result: dict) -> str:
    """One plain-English sentence for provenance / HITL."""
    status = result.get("status")
    if status == "MATCHED":
        return "Three-way match passed: invoice quantities and prices agree with the purchase order and goods receipt within tolerance."
    if status == "PENDING_RECEIPT":
        return "Three-way match pending: the purchase order is linked but no goods receipt has been recorded yet."
    if status == "NO_PO":
        return "Three-way match not applicable: no purchase order is linked to this invoice."
    reasons = "; ".join(result.get("reasons") or []) or "one or more legs failed reconciliation"
    return f"Three-way match exception: {reasons}"
