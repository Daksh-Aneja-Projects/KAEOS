"""KAEOS Finance — governed vendor payments that actually reach the ledger.

The first real P2P money event wired end to end: recording a payment creates
the Payment row, reduces the invoice balance, and POSTS the journal entry
through the GL keystone - one transaction, fail-closed. The Payment model
always had a `journal_entry_id` column; nothing ever wrote it.

Controls:
  * The invoice must be APPROVED with a recorded approver before any payment.
  * Four-eyes: the payer may not be the invoice's approver.
  * Overpayment is refused; amounts are Decimal cents.

Accounting basis: CASH BASIS for this increment - the payment posts
DR expense / CR cash, recognizing the expense when paid. The accrual upgrade
(invoice approval posts DR expense / CR accounts-payable, payment posts
DR accounts-payable / CR cash) belongs with the invoice-approval GL hook.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy import func as sqlfunc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.finance.models.accounts_payable import (
    Invoice,
    InvoiceStatus,
    Payment,
    PaymentMethod,
    PaymentStatus,
)
from app.finance.models.core import AccountType, ChartOfAccount
from app.finance.services.gl import GLPostingError, _money, post_journal_entry

logger = logging.getLogger(__name__)


class PaymentError(ValueError):
    """The payment violates a control and was NOT recorded."""


async def _find_account(
    db: AsyncSession, tenant_id: str, *,
    account_id: Optional[str] = None,
    preferred_codes: tuple[str, ...] = (),
    account_type: Optional[AccountType] = None,
    bank: bool = False,
) -> ChartOfAccount:
    if account_id:
        acc = (await db.execute(select(ChartOfAccount).where(
            ChartOfAccount.id == account_id,
            ChartOfAccount.tenant_id == tenant_id,
            ChartOfAccount.is_active == True,  # noqa: E712
        ))).scalar_one_or_none()
        if acc:
            return acc
    for code in preferred_codes:
        acc = (await db.execute(select(ChartOfAccount).where(
            ChartOfAccount.tenant_id == tenant_id,
            ChartOfAccount.account_code == code,
            ChartOfAccount.is_active == True,  # noqa: E712
        ))).scalar_one_or_none()
        if acc:
            return acc
    q = select(ChartOfAccount).where(
        ChartOfAccount.tenant_id == tenant_id,
        ChartOfAccount.is_active == True,  # noqa: E712
    )
    if bank:
        q = q.where(ChartOfAccount.is_bank_account == True)  # noqa: E712
    if account_type is not None:
        q = q.where(ChartOfAccount.account_type == account_type)
    acc = (await db.execute(q.order_by(ChartOfAccount.account_code))).scalars().first()
    if acc is None:
        kind = "bank/cash" if bank else (account_type.value if account_type else "GL")
        raise PaymentError(
            f"no active {kind} account in the chart of accounts; "
            "set one up before recording payments"
        )
    return acc


async def record_vendor_payment(
    db: AsyncSession,
    tenant_id: str,
    *,
    invoice_id: str,
    amount,
    method: str = "ACH",
    reference_number: Optional[str] = None,
    bank_account_id: Optional[str] = None,
    recorded_by: Optional[str] = None,
) -> Payment:
    """Record a vendor payment and post it to the GL - one atomic commit.

    Raises PaymentError / GLPostingError with NOTHING recorded on any
    control violation.
    """
    invoice = (await db.execute(select(Invoice).where(
        Invoice.id == invoice_id, Invoice.tenant_id == tenant_id,
    ))).scalar_one_or_none()
    if invoice is None:
        raise PaymentError("invoice not found")
    if invoice.status not in (InvoiceStatus.APPROVED, InvoiceStatus.OVERDUE):
        raise PaymentError(
            f"invoice {invoice.invoice_number} is "
            f"{getattr(invoice.status, 'value', invoice.status)}; only an "
            "APPROVED (or OVERDUE-approved) invoice can be paid"
        )
    if not invoice.approved_by:
        raise PaymentError(
            f"invoice {invoice.invoice_number} carries no approver identity; "
            "approval must be recorded before payment"
        )
    if recorded_by and invoice.approved_by == recorded_by:
        raise PaymentError(
            "Four-eyes: the identity that approved this invoice cannot also "
            "pay it. Ask a different operator to record the payment."
        )

    pay_amount = _money(amount)
    if pay_amount <= 0:
        raise PaymentError("payment amount must be positive")
    balance = Decimal(str(invoice.balance_due or 0))
    if pay_amount > balance:
        raise PaymentError(
            f"payment {pay_amount} exceeds the invoice balance {balance}"
        )

    cash = await _find_account(
        db, tenant_id, account_id=bank_account_id,
        preferred_codes=("1010", "1000"), account_type=AccountType.ASSET, bank=True,
    )
    expense = await _find_account(
        db, tenant_id, account_id=invoice.gl_account_id,
        preferred_codes=("6000",), account_type=AccountType.EXPENSE,
    )

    year = datetime.now(timezone.utc).year
    count = (await db.execute(select(sqlfunc.count(Payment.id)).where(
        Payment.tenant_id == tenant_id))).scalar() or 0
    payment = Payment(
        tenant_id=tenant_id,
        vendor_id=invoice.vendor_id,
        invoice_id=invoice.id,
        payment_number=f"PAY-{year}-{count + 1:06d}",
        payment_date=datetime.now(timezone.utc).date(),
        amount=pay_amount,
        currency=invoice.currency or "USD",
        method=PaymentMethod(method) if not isinstance(method, PaymentMethod) else method,
        status=PaymentStatus.COMPLETED,
        bank_account_id=bank_account_id,
        reference_number=reference_number,
    )
    db.add(payment)

    # Invoice state rides in the same pending transaction as the entry.
    invoice.amount_paid = (Decimal(str(invoice.amount_paid or 0)) + pay_amount)
    invoice.balance_due = balance - pay_amount
    if invoice.balance_due == 0:
        invoice.status = InvoiceStatus.PAID

    # The keystone commits the session: payment + invoice update + entry +
    # lines + balances + signed provenance land together or not at all.
    entry = await post_journal_entry(
        db, tenant_id,
        lines=[
            {"account_id": expense.id, "debit": pay_amount,
             "description": f"Invoice {invoice.invoice_number}"},
            {"account_id": cash.id, "credit": pay_amount,
             "description": f"Payment {payment.payment_number}"},
        ],
        description=(f"Vendor payment {payment.payment_number} against "
                     f"invoice {invoice.invoice_number}"),
        reference=invoice.invoice_number,
        source_module="AP",
        source_document_id=payment.id,
        created_by=recorded_by,
    )
    # Back-link both documents to their entry (small follow-up commit; the
    # entry's source_document_id already ties them even if this write is lost).
    payment.journal_entry_id = entry.id
    invoice.journal_entry_id = entry.id
    await db.commit()

    logger.info("[AP] payment %s: %s against %s -> JE %s",
                payment.payment_number, pay_amount, invoice.invoice_number,
                entry.entry_number)
    return payment
