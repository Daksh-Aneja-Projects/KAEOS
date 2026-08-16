"""APAgent: the deterministic matcher decides three_way_match_status, not the LLM.

run_gated_finance_skill is stubbed so no real Ollama call happens and so we can
prove the LLM's claimed match is ignored - the persisted status comes from the
reconciliation of PO/receipt/invoice.
"""
import uuid
from datetime import date, timedelta

from sqlalchemy import select

from app.finance.agents.ap_agent import APAgent
from app.finance.models.accounts_payable import Invoice, InvoiceStatus, Vendor
from app.models.domain import ProvenanceLedger
from app.operations.models.procurement import (
    GoodsReceipt,
    POLineItem,
    ProcurementStatus,
    PurchaseOrder,
)


def _t():
    return f"tenant_ap_{uuid.uuid4().hex[:6]}"


async def _chain(db, tenant, *, inv_price="3545.00"):
    vendor = Vendor(id=str(uuid.uuid4()), tenant_id=tenant, name="AWS",
                    vendor_code=f"V-{uuid.uuid4().hex[:6]}")
    po = PurchaseOrder(id=str(uuid.uuid4()), tenant_id=tenant,
                       po_number=f"PO-{uuid.uuid4().hex[:6]}", vendor_name="AWS",
                       vendor_id=vendor.id, total_amount=35450.00,
                       status=ProcurementStatus.RECEIVED)
    db.add_all([vendor, po])
    await db.flush()
    line = POLineItem(id=str(uuid.uuid4()), tenant_id=tenant, purchase_order_id=po.id,
                      line_number=1, description="compute", quantity=10,
                      unit_price="3545.00", amount=35450.00)
    db.add(line)
    await db.flush()
    db.add(GoodsReceipt(id=str(uuid.uuid4()), tenant_id=tenant, purchase_order_id=po.id,
                        po_line_item_id=line.id, receiver_name="rcv", received_quantity=10))
    inv = Invoice(
        id=str(uuid.uuid4()), tenant_id=tenant, vendor_id=vendor.id,
        invoice_number=f"INV-{uuid.uuid4().hex[:6]}", status=InvoiceStatus.PENDING_APPROVAL,
        subtotal=float(inv_price) * 10, total_amount=float(inv_price) * 10,
        balance_due=float(inv_price) * 10, invoice_date=date.today(),
        due_date=date.today() + timedelta(days=30), purchase_order_id=po.id,
        line_items=[{"qty": 10, "unit_price": float(inv_price), "po_line_item_id": line.id}],
    )
    db.add(inv)
    await db.commit()
    return inv.id, po.id


def _stub_llm(monkeypatch, *, three_way="MATCHED", recommendation="APPROVE"):
    async def _fake(*args, **kwargs):
        return {
            "status": "SUCCESS_CLEAN",
            "execution_id": "exec-test",
            "reasoning_chain": [{"decision": (
                '{"recommendation": "%s", "three_way_match": "%s", '
                '"confidence": 0.95, "duplicate_risk": "LOW"}' % (recommendation, three_way)
            )}],
        }
    monkeypatch.setattr("app.finance.agents.ap_agent.run_gated_finance_skill", _fake)


async def test_llm_cannot_fake_a_match(db, monkeypatch):
    """Over-tolerance invoice -> EXCEPTION even though the stubbed LLM says MATCHED+APPROVE."""
    tenant = _t()
    invoice_id, po_id = await _chain(db, tenant, inv_price="3899.50")  # 10% over
    _stub_llm(monkeypatch, three_way="MATCHED", recommendation="APPROVE")

    await APAgent().process_invoice(db, invoice_id, tenant)

    db.expire_all()
    inv = (await db.execute(select(Invoice).where(Invoice.id == invoice_id))).scalar_one()
    assert inv.three_way_match_status == "EXCEPTION"
    assert inv.status == InvoiceStatus.DISPUTED  # never auto-approved

    # Provenance recorded the control with the PO + invoice as evidence.
    rows = (await db.execute(select(ProvenanceLedger).where(
        ProvenanceLedger.tenant_id == tenant,
        ProvenanceLedger.event_type == "THREE_WAY_MATCH"))).scalars().all()
    assert len(rows) == 1
    assert po_id in (rows[0].evidence_ids or [])


async def test_real_gate_blocks_humanless_approval(db):
    """No gate stub: the SOX four-eyes gate blocks the humanless financial action
    at compliance (BLOCKED_COMPLIANCE), so the agent never reaches an auto-approve
    path - proof the removed auto-approve+accrual branch is unreachable dead code.
    Even a clean MATCHED invoice lands DISPUTED, is never APPROVED, and no accrual
    journal entry is posted off-books."""
    from app.finance.models.core import JournalEntry

    tenant = _t()
    invoice_id, _ = await _chain(db, tenant, inv_price="3545.00")  # MATCHED

    result = await APAgent().process_invoice(db, invoice_id, tenant)
    assert result.get("status") == "BLOCKED_COMPLIANCE"

    db.expire_all()
    inv = (await db.execute(select(Invoice).where(Invoice.id == invoice_id))).scalar_one()
    assert inv.status == InvoiceStatus.DISPUTED
    assert inv.status != InvoiceStatus.APPROVED
    assert inv.approved_by is None
    # The dead branch's off-books accrual side effect is gone: nothing posted.
    jes = (await db.execute(select(JournalEntry).where(
        JournalEntry.tenant_id == tenant))).scalars().all()
    assert jes == []


async def test_clean_invoice_matches(db, monkeypatch):
    tenant = _t()
    invoice_id, _ = await _chain(db, tenant, inv_price="3545.00")  # exact
    _stub_llm(monkeypatch, three_way="EXCEPTION", recommendation="REJECT")

    await APAgent().process_invoice(db, invoice_id, tenant)

    db.expire_all()
    inv = (await db.execute(select(Invoice).where(Invoice.id == invoice_id))).scalar_one()
    # LLM said EXCEPTION; the matcher computed MATCHED and wins.
    assert inv.three_way_match_status == "MATCHED"
