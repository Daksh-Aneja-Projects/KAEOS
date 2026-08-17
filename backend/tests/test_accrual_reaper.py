"""§20 accrual reaper: an APPROVED invoice that inline accrual retry never
reached must be booked by the scheduled sweep, and a second run must not
double-post. The reaper runs on the owner (maintenance) session, so this test
seeds and reads on that same engine and forces leader=True (as the job_queue
reaper tests do).
"""
import uuid
from datetime import date, timedelta

from sqlalchemy import select

from app.core.database import MaintenanceSessionLocal
from app.finance.models.accounts_payable import Invoice, InvoiceStatus, Vendor
from app.finance.models.core import AccountType, ChartOfAccount, JournalEntry
from app.services import scheduler


async def _seed_approved_unaccrued(db, tenant):
    db.add_all([
        ChartOfAccount(tenant_id=tenant, account_code="6000", account_name="Vendor Expense",
                       account_type=AccountType.EXPENSE, normal_balance="DEBIT"),
        ChartOfAccount(tenant_id=tenant, account_code="2000", account_name="Accounts Payable",
                       account_type=AccountType.LIABILITY, normal_balance="CREDIT"),
    ])
    vendor = Vendor(id=str(uuid.uuid4()), tenant_id=tenant, name="AWS",
                    vendor_code=f"V-{uuid.uuid4().hex[:6]}")
    db.add(vendor)
    await db.commit()
    invoice = Invoice(
        id=str(uuid.uuid4()), tenant_id=tenant, vendor_id=vendor.id,
        invoice_number=f"INV-{uuid.uuid4().hex[:6]}", status=InvoiceStatus.APPROVED,
        subtotal=1000, total_amount=1000, balance_due=1000,
        invoice_date=date.today() - timedelta(days=5),
        due_date=date.today() + timedelta(days=25),
        approved_by="cfo@acme",
    )
    db.add(invoice)
    await db.commit()
    return invoice.id


async def _accrual_entries(db, invoice_id):
    return (await db.execute(select(JournalEntry).where(
        JournalEntry.source_module == "AP_ACCRUAL",
        JournalEntry.source_document_id == invoice_id,
    ))).scalars().all()


async def test_accrual_reaper_books_then_does_not_double_post(monkeypatch):
    monkeypatch.setattr(scheduler, "_is_leader", lambda: True)
    tenant = f"tenant_accr_{uuid.uuid4().hex[:6]}"

    async with MaintenanceSessionLocal() as db:
        invoice_id = await _seed_approved_unaccrued(db, tenant)
        assert await _accrual_entries(db, invoice_id) == []  # off-books before the sweep

    await scheduler.run_accrual_reaper()
    async with MaintenanceSessionLocal() as db:
        first = await _accrual_entries(db, invoice_id)
    assert len(first) == 1, "reaper must accrue the approved-but-unaccrued invoice"

    # Idempotent: a second sweep re-selects nothing (and even if it did, accrue_invoice
    # guards on the existing entry) so no second liability is posted.
    await scheduler.run_accrual_reaper()
    async with MaintenanceSessionLocal() as db:
        second = await _accrual_entries(db, invoice_id)
    assert len(second) == 1, "second run must NOT double-post the accrual"
    assert second[0].id == first[0].id
