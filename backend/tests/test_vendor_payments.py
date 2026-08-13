"""Governed vendor payments (Phase 3): the first P2P money event that
actually reaches the ledger - controls first, cash-basis GL posting, one
atomic commit."""
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
from app.finance.services.payments import PaymentError, record_vendor_payment


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
    vendor = Vendor(id=str(uuid.uuid4()), tenant_id=tenant, name="AWS",
                    vendor_code=f"V-{uuid.uuid4().hex[:6]}")
    db.add_all([cash, expense, vendor])
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
    return cash, expense, vendor, invoice


async def test_payment_posts_to_the_gl_atomically(db):
    tenant = _t()
    cash, expense, _, invoice = await _fixture(db, tenant)
    cash_id, expense_id, invoice_id = cash.id, expense.id, invoice.id

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

    entry = (await db.execute(select(JournalEntry).where(
        JournalEntry.id == je_id))).scalar_one()
    assert float(entry.total_debit) == 600.00 == float(entry.total_credit)

    cash = (await db.execute(select(ChartOfAccount).where(
        ChartOfAccount.id == cash_id))).scalar_one()
    expense = (await db.execute(select(ChartOfAccount).where(
        ChartOfAccount.id == expense_id))).scalar_one()
    assert Decimal(str(cash.current_balance)) == Decimal("-600.00")   # cash out
    assert Decimal(str(expense.current_balance)) == Decimal("600.00")  # expense up


async def test_full_payment_marks_the_invoice_paid(db):
    tenant = _t()
    _, _, _, invoice = await _fixture(db, tenant)
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
    _, _, _, invoice = await _fixture(db, tenant)
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
    _, _, _, invoice = await _fixture(db, tenant, status=InvoiceStatus.PENDING_APPROVAL)
    with pytest.raises(PaymentError, match="APPROVED"):
        await record_vendor_payment(db, tenant, invoice_id=invoice.id,
                                    amount=100, recorded_by="x@acme")
    await db.rollback()


async def test_four_eyes_the_approver_cannot_pay(db):
    tenant = _t()
    _, _, _, invoice = await _fixture(db, tenant, approved_by="cfo@acme")
    with pytest.raises(PaymentError, match="Four-eyes"):
        await record_vendor_payment(db, tenant, invoice_id=invoice.id,
                                    amount=100, recorded_by="cfo@acme")
    await db.rollback()
    assert (await db.execute(select(Payment).where(
        Payment.tenant_id == tenant))).scalars().all() == []
