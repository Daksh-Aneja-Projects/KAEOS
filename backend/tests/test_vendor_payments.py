"""Governed vendor payments (Phase 3): the first P2P money event that
actually reaches the ledger - controls first, accrual-basis GL posting, one
atomic commit. Approving an invoice accrues it (DR expense / CR AP); a payment
settles the payable (DR AP / CR cash)."""
import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.finance.models.accounts_payable import (
    Invoice,
    InvoiceStatus,
    Payment,
    Vendor,
)
from app.finance.models.core import AccountType, ChartOfAccount, JournalEntry
from app.finance.services.payments import (
    PaymentError,
    accrue_invoice,
    record_vendor_payment,
)


def _t():
    return f"tenant_pay_{uuid.uuid4().hex[:6]}"


async def _fixture(db, tenant, *, approved_by="cfo@acme", status=InvoiceStatus.APPROVED):
    cash = ChartOfAccount(tenant_id=tenant, account_code="1010",
                          account_name="Operating Cash",
                          account_type=AccountType.ASSET,
                          normal_balance="DEBIT", is_bank_account=True)
    expense = ChartOfAccount(tenant_id=tenant, account_code="6000",
                             account_name="Vendor Expense",
                             account_type=AccountType.EXPENSE,
                             normal_balance="DEBIT")
    ap = ChartOfAccount(tenant_id=tenant, account_code="2000",
                        account_name="Accounts Payable",
                        account_type=AccountType.LIABILITY,
                        normal_balance="CREDIT")
    vendor = Vendor(id=str(uuid.uuid4()), tenant_id=tenant, name="AWS",
                    vendor_code=f"V-{uuid.uuid4().hex[:6]}")
    db.add_all([cash, expense, ap, vendor])
    await db.commit()
    invoice = Invoice(
        id=str(uuid.uuid4()), tenant_id=tenant, vendor_id=vendor.id,
        invoice_number=f"INV-{uuid.uuid4().hex[:6]}", status=status,
        subtotal=1000, total_amount=1000, balance_due=1000,
        invoice_date=date.today() - timedelta(days=5),
        due_date=date.today() + timedelta(days=25),
        approved_by=approved_by,
    )
    db.add(invoice)
    await db.commit()
    return cash, expense, ap, vendor, invoice


async def test_payment_posts_to_the_gl_atomically(db):
    tenant = _t()
    cash, expense, ap, _, invoice = await _fixture(db, tenant)
    cash_id, expense_id, ap_id, invoice_id = cash.id, expense.id, ap.id, invoice.id

    payment = await record_vendor_payment(
        db, tenant, invoice_id=invoice_id, amount=600.00,
        recorded_by="ap-clerk@acme")

    assert payment.payment_number.startswith("PAY-")
    assert payment.journal_entry_id
    je_id = payment.journal_entry_id

    db.expire_all()
    invoice = (await db.execute(select(Invoice).where(
        Invoice.id == invoice_id))).scalar_one()
    assert Decimal(str(invoice.balance_due)) == Decimal("400.00")
    assert invoice.status == InvoiceStatus.APPROVED  # partially paid

    # The payment entry settles the payable: DR AP 600 / CR cash 600.
    entry = (await db.execute(select(JournalEntry).where(
        JournalEntry.id == je_id))).scalar_one()
    assert float(entry.total_debit) == 600.00 == float(entry.total_credit)

    cash = (await db.execute(select(ChartOfAccount).where(
        ChartOfAccount.id == cash_id))).scalar_one()
    expense = (await db.execute(select(ChartOfAccount).where(
        ChartOfAccount.id == expense_id))).scalar_one()
    ap = (await db.execute(select(ChartOfAccount).where(
        ChartOfAccount.id == ap_id))).scalar_one()
    # Accrual booked the full liability up front, the payment settled part of it.
    assert Decimal(str(cash.current_balance)) == Decimal("-600.00")    # cash out
    assert Decimal(str(expense.current_balance)) == Decimal("1000.00")  # full expense accrued
    assert Decimal(str(ap.current_balance)) == Decimal("400.00")       # payable remaining


async def test_full_payment_marks_the_invoice_paid(db):
    tenant = _t()
    _, _, _, _, invoice = await _fixture(db, tenant)
    invoice_id = invoice.id
    await record_vendor_payment(db, tenant, invoice_id=invoice_id,
                                amount=1000, recorded_by="ap-clerk@acme")
    db.expire_all()
    invoice = (await db.execute(select(Invoice).where(
        Invoice.id == invoice_id))).scalar_one()
    assert invoice.status == InvoiceStatus.PAID
    assert Decimal(str(invoice.balance_due)) == Decimal("0.00")


async def test_controls_refuse_bad_payments(db):
    tenant = _t()
    _, _, _, _, invoice = await _fixture(db, tenant)
    invoice_id = invoice.id

    with pytest.raises(PaymentError, match="exceeds"):
        await record_vendor_payment(db, tenant, invoice_id=invoice_id,
                                    amount=1000.01, recorded_by="x@acme")
    await db.rollback()
    with pytest.raises(PaymentError, match="positive"):
        await record_vendor_payment(db, tenant, invoice_id=invoice_id,
                                    amount=0, recorded_by="x@acme")
    await db.rollback()
    # No payment or entry landed.
    assert (await db.execute(select(Payment).where(
        Payment.tenant_id == tenant))).scalars().all() == []


async def test_unapproved_invoice_cannot_be_paid(db):
    tenant = _t()
    _, _, _, _, invoice = await _fixture(db, tenant, status=InvoiceStatus.PENDING_APPROVAL)
    with pytest.raises(PaymentError, match="APPROVED"):
        await record_vendor_payment(db, tenant, invoice_id=invoice.id,
                                    amount=100, recorded_by="x@acme")
    await db.rollback()


async def test_four_eyes_the_approver_cannot_pay(db):
    tenant = _t()
    _, _, _, _, invoice = await _fixture(db, tenant, approved_by="cfo@acme")
    with pytest.raises(PaymentError, match="Four-eyes"):
        await record_vendor_payment(db, tenant, invoice_id=invoice.id,
                                    amount=100, recorded_by="cfo@acme")
    await db.rollback()
    assert (await db.execute(select(Payment).where(
        Payment.tenant_id == tenant))).scalars().all() == []


async def test_match_exception_blocks_payment(db):
    """An EXCEPTION three-way match refuses payment and posts NOTHING."""
    tenant = _t()
    _, _, _, _, invoice = await _fixture(db, tenant)
    invoice.three_way_match_status = "EXCEPTION"
    db.add(invoice)
    await db.commit()
    invoice_id = invoice.id

    with pytest.raises(PaymentError, match="three-way match"):
        await record_vendor_payment(db, tenant, invoice_id=invoice_id,
                                    amount=100, recorded_by="ap-clerk@acme")
    await db.rollback()
    assert (await db.execute(select(Payment).where(
        Payment.tenant_id == tenant))).scalars().all() == []
    assert (await db.execute(select(JournalEntry).where(
        JournalEntry.tenant_id == tenant))).scalars().all() == []


async def test_match_exception_pays_with_distinct_override(db):
    """A recorded human override (distinct from the payer) releases the payment."""
    tenant = _t()
    _, _, _, _, invoice = await _fixture(db, tenant)
    invoice.three_way_match_status = "EXCEPTION"
    db.add(invoice)
    await db.commit()
    invoice_id = invoice.id

    # Same identity as payer is not a valid override.
    with pytest.raises(PaymentError, match="three-way match"):
        await record_vendor_payment(db, tenant, invoice_id=invoice_id, amount=100,
                                    recorded_by="ap-clerk@acme",
                                    match_override_by="ap-clerk@acme")
    await db.rollback()

    payment = await record_vendor_payment(
        db, tenant, invoice_id=invoice_id, amount=100,
        recorded_by="ap-clerk@acme", match_override_by="controller@acme")
    assert payment.journal_entry_id


async def test_accrual_is_idempotent(db):
    """Accruing at approval then paying must not double-book the expense."""
    tenant = _t()
    _, expense, ap, _, invoice = await _fixture(db, tenant)
    expense_id, ap_id, invoice_id = expense.id, ap.id, invoice.id

    first = await accrue_invoice(db, tenant, invoice, actor="cfo@acme")
    assert first is not None
    # Pay in full: settles the payable, must NOT re-accrue the expense.
    await record_vendor_payment(db, tenant, invoice_id=invoice_id,
                                amount=1000, recorded_by="ap-clerk@acme")

    accruals = (await db.execute(select(JournalEntry).where(
        JournalEntry.tenant_id == tenant,
        JournalEntry.source_module == "AP_ACCRUAL"))).scalars().all()
    assert len(accruals) == 1, "invoice must be accrued exactly once"

    db.expire_all()
    expense = (await db.execute(select(ChartOfAccount).where(
        ChartOfAccount.id == expense_id))).scalar_one()
    ap = (await db.execute(select(ChartOfAccount).where(
        ChartOfAccount.id == ap_id))).scalar_one()
    assert Decimal(str(expense.current_balance)) == Decimal("1000.00")  # accrued once
    assert Decimal(str(ap.current_balance)) == Decimal("0.00")          # payable cleared
