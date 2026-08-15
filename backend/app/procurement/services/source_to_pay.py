"""KAEOS Procurement - source-to-pay orchestration service.

Binds the source-to-pay flow (requisition -> PO -> goods receipt -> three-way
match) on top of the EXISTING Operations ``ops_*`` procurement tables, the
Finance three-way-match service, and the four procurement control checkers used
as REAL gates. No new tables.

Approval / settlement is fail-closed: a purchase order is approved only when
every applicable control PASSES:

  * SPEND_AUTHORIZATION   - amount within the approver's delegated limit
  * SEGREGATION_OF_DUTIES - requester / approver / receiver are distinct
  * THREE_WAY_MATCH       - any linked invoice reconciles with PO + receipt
  * OFAC_SANCTIONS        - the vendor is not on the supplied denied-parties list

A control that returns anything other than PASS / NOT_APPLICABLE (a real BLOCK,
or an ADVISORY meaning it could not verify) prevents approval - absent evidence
is treated as the stricter prior, never a silent pass. Every attempt appends a
signed provenance ledger event first.

Money is Decimal. Every query is tenant-scoped; another tenant's row is a 404
(``ProcurementNotFound``).
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.compliance.base import CheckResult, CheckStatus
from app.compliance.checkers.procurement import (
    check_ofac_sanctions,
    check_segregation_of_duties,
    check_spend_authorization,
)
from app.finance.services.three_way_match import evaluate_three_way_match
from app.operations.models.procurement import (
    GoodsReceipt,
    ProcurementStatus,
    PurchaseOrder,
    PurchaseRequest,
)
from app.services.provenance import append_ledger_event

# States from which a PO may still be approved.
_APPROVABLE = {ProcurementStatus.DRAFT, ProcurementStatus.PENDING_APPROVAL}


class ProcurementError(ValueError):
    """Base procurement domain error; router maps to 4xx."""


class ProcurementNotFound(ProcurementError):
    """Referenced entity absent (or another tenant's) -> 404."""


class ProcurementBlocked(ProcurementError):
    """A control gate refused the action -> 409. Carries the blocking checks."""

    def __init__(self, gates: list[dict]):
        self.gates = gates
        blocked = [g for g in gates if g["blocking"]]
        codes = ", ".join(g["code"] for g in blocked) or "control"
        reasons = "; ".join(r for g in blocked for r in g["reasons"])
        super().__init__(f"Blocked by {codes}: {reasons}")


def _gate(cr: CheckResult) -> dict:
    """Normalize a CheckResult into a gate row. A gate is 'blocking' unless it
    verifiably PASSED or does not apply - absent evidence keeps the stricter
    prior (fail-closed)."""
    ok = cr.passed
    return {
        "code": cr.framework,
        "status": cr.status.value,
        "blocking": not ok,
        "reasons": [f.message for f in cr.findings],
    }


async def _load_po(db: AsyncSession, tenant_id: str, po_id: str) -> PurchaseOrder:
    po = (await db.execute(select(PurchaseOrder).where(
        PurchaseOrder.id == po_id, PurchaseOrder.tenant_id == tenant_id
    ))).scalar_one_or_none()
    if po is None:
        raise ProcurementNotFound(f"Purchase order {po_id} not found")
    return po


async def _receiver_of(db: AsyncSession, tenant_id: str, po_id: str) -> Optional[str]:
    r = (await db.execute(select(GoodsReceipt.receiver_name).where(
        GoodsReceipt.purchase_order_id == po_id, GoodsReceipt.tenant_id == tenant_id
    ).limit(1))).scalar_one_or_none()
    return r


async def _requester_of(db: AsyncSession, tenant_id: str, po: PurchaseOrder) -> Optional[str]:
    if not po.purchase_request_id:
        return None
    return (await db.execute(select(PurchaseRequest.requested_by).where(
        PurchaseRequest.id == po.purchase_request_id,
        PurchaseRequest.tenant_id == tenant_id,
    ))).scalar_one_or_none()


async def _three_way_match_gate(db: AsyncSession, tenant_id: str, po_id: str) -> CheckResult:
    """Run the Finance three-way match against every invoice linked to this PO
    and fold the worst outcome into a THREE_WAY_MATCH CheckResult. No linked
    invoice = nothing to bill yet = NOT_APPLICABLE (approval may precede an
    invoice; settlement re-runs this)."""
    from app.compliance.base import Finding
    from app.finance.models.accounts_payable import Invoice
    from app.finance.services.three_way_match import match_summary

    invoices = (await db.execute(select(Invoice).where(
        Invoice.purchase_order_id == po_id, Invoice.tenant_id == tenant_id
    ))).scalars().all()
    if not invoices:
        return CheckResult("THREE_WAY_MATCH", CheckStatus.NOT_APPLICABLE, [],
                           method="deterministic")

    findings: list[Finding] = []
    advisory: list[Finding] = []
    for inv in invoices:
        res = await evaluate_three_way_match(db, tenant_id, inv)
        if res["status"] == "EXCEPTION":
            findings.append(Finding("twm_exception", match_summary(res), "HIGH"))
        elif res["status"] in ("PENDING_RECEIPT", "NO_PO"):
            advisory.append(Finding("twm_unverifiable", match_summary(res), "MEDI"))
    if findings:
        return CheckResult("THREE_WAY_MATCH", CheckStatus.BLOCK, findings + advisory,
                           method="deterministic")
    if advisory:
        return CheckResult("THREE_WAY_MATCH", CheckStatus.ADVISORY, advisory,
                           method="deterministic")
    return CheckResult("THREE_WAY_MATCH", CheckStatus.PASS, [], method="deterministic")


async def evaluate_po_gates(
    db: AsyncSession,
    tenant_id: str,
    po: PurchaseOrder,
    *,
    approver: str,
    approver_limit: Optional[Any] = None,
    sanctions_list: Optional[list] = None,
    requester: Optional[str] = None,
    receiver: Optional[str] = None,
) -> list[dict]:
    """Run the four procurement controls against a PO and return gate rows.

    ``requester`` / ``receiver`` default to the PO's own requisition requester
    and recorded goods-receipt receiver so segregation of duties is checked
    against the real people, not client-supplied strings.
    """
    requester = requester or await _requester_of(db, tenant_id, po)
    receiver = receiver or await _receiver_of(db, tenant_id, po.id)

    spend = check_spend_authorization({"authorization": {
        "amount": Decimal(str(po.total_amount or 0)),
        "approver_limit": approver_limit,
        "approver": approver,
    }})
    sod = check_segregation_of_duties({"roles": {
        "requester": requester, "approver": approver, "receiver": receiver,
    }})
    ofac = check_ofac_sanctions({
        "vendor": {"name": po.vendor_name, "id": po.vendor_id},
        "sanctions_list": sanctions_list,
    })
    twm = await _three_way_match_gate(db, tenant_id, po.id)
    return [_gate(cr) for cr in (spend, sod, twm, ofac)]


async def approve_purchase_order(
    db: AsyncSession,
    tenant_id: str,
    po_id: str,
    *,
    approver: str,
    approver_limit: Optional[Any] = None,
    sanctions_list: Optional[list] = None,
    requester: Optional[str] = None,
    receiver: Optional[str] = None,
) -> dict:
    """Approve a PO only if all four controls pass. Fail-closed: on any blocking
    gate the PO stays PENDING_APPROVAL and ``ProcurementBlocked`` is raised. The
    attempt (approved or blocked) is written to the signed provenance ledger."""
    po = await _load_po(db, tenant_id, po_id)
    if po.status not in _APPROVABLE:
        raise ProcurementBlocked([{
            "code": "PO_STATE", "status": "BLOCK", "blocking": True,
            "reasons": [f"Purchase order is {po.status.value}, not awaiting approval."],
        }])

    gates = await evaluate_po_gates(
        db, tenant_id, po, approver=approver, approver_limit=approver_limit,
        sanctions_list=sanctions_list, requester=requester, receiver=receiver)
    blocked = [g for g in gates if g["blocking"]]

    verdict = "BLOCKED" if blocked else "APPROVED"
    reasons = "; ".join(r for g in blocked for r in g["reasons"]) or "all controls passed"
    await append_ledger_event(
        db, tenant_id=tenant_id, event_type=f"PO_APPROVAL_{verdict}",
        reasoning=(f"Source-to-pay approval of PO {po.po_number} by {approver}: "
                   f"{verdict.lower()} ({reasons})."),
        evidence_ids=[po.id],
        scope=po.id,
        commit=False,
    )
    if blocked:
        # Persist the ledger row for the blocked attempt without approving.
        await db.commit()
        raise ProcurementBlocked(gates)

    po.status = ProcurementStatus.APPROVED
    db.add(po)
    await db.commit()
    return {"po_id": po.id, "po_number": po.po_number,
            "status": po.status.value, "gates": gates}


async def screen_vendor(vendor_name: str, sanctions_list: Optional[list]) -> dict:
    """OFAC / denied-parties screen for a vendor. Returns the gate row; a hit is
    ``blocking=True``."""
    cr = check_ofac_sanctions({"vendor": {"name": vendor_name},
                               "sanctions_list": sanctions_list})
    return _gate(cr)


async def run_three_way_match(db: AsyncSession, tenant_id: str, po_id: str) -> dict:
    """Reconcile every invoice linked to a PO against its receipts (Finance
    three-way match). 404 if the PO is absent / another tenant's."""
    await _load_po(db, tenant_id, po_id)
    from app.finance.models.accounts_payable import Invoice

    invoices = (await db.execute(select(Invoice).where(
        Invoice.purchase_order_id == po_id, Invoice.tenant_id == tenant_id
    ))).scalars().all()
    results = [{"invoice_id": inv.id, "invoice_number": inv.invoice_number,
                **(await evaluate_three_way_match(db, tenant_id, inv))}
               for inv in invoices]
    return {"po_id": po_id, "invoice_count": len(results), "matches": results}
