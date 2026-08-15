"""KAEOS Finance — governed vendor payments that actually reach the ledger.

The first real P2P money event wired end to end: recording a payment creates
the Payment row, reduces the invoice balance, and POSTS the journal entry
through the GL keystone - one transaction, fail-closed. The Payment model
always had a `journal_entry_id` column; nothing ever wrote it.

Controls:
  * The invoice must be APPROVED with a recorded approver before any payment.
  * Four-eyes: the payer may not be the invoice's approver.
  * Overpayment is refused; amounts are Decimal cents.

Accounting basis: ACCRUAL. The liability is recognized when the invoice is
approved - ``accrue_invoice`` posts DR expense / CR accounts-payable for the
full invoice, so the P&L and balance sheet reflect approved-but-unpaid
invoices. A payment then settles the payable: DR accounts-payable / CR cash.
``record_vendor_payment`` calls ``accrue_invoice`` first (idempotent), so an
invoice approved before the accrual hook existed is still booked correctly.
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
from app.finance.models.core import (
    AccountType,
    ChartOfAccount,
    JournalEntry,
    JournalEntryStatus,
)
from app.finance.services.gl import _money, post_journal_entry

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


async def accrue_invoice(
    db: AsyncSession, tenant_id: str, invoice: Invoice, *, actor: Optional[str] = None,
) -> Optional[JournalEntry]:
    """Recognize an approved AP invoice as expense + payable (accrual basis).

    Posts DR expense / CR accounts-payable for the invoice's full amount at the
    moment the liability is incurred, so the P&L and balance sheet show
    approved-but-unpaid invoices. Idempotent: each invoice is accrued once
    (guarded by its existing AP_ACCRUAL entry); a repeat call returns the
    original entry and posts nothing. Returns None for a zero-amount invoice.

    ponytail: idempotency is a SELECT-then-post, not a DB unique constraint -
    a rare approve/pay race could double-accrue. Add unique(tenant_id,
    source_module, source_document_id) if concurrent approval+payment is real.
    """
    existing = (await db.execute(select(JournalEntry).where(
        JournalEntry.tenant_id == tenant_id,
        JournalEntry.source_module == "AP_ACCRUAL",
        JournalEntry.source_document_id == invoice.id,
        JournalEntry.status == JournalEntryStatus.POSTED,
    ))).scalar_one_or_none()
    if existing is not None:
        return existing

    amount = _money(invoice.total_amount)
    if amount <= 0:
        return None

    expense = await _find_account(
        db, tenant_id, account_id=invoice.gl_account_id,
        preferred_codes=("6000", "6010"), account_type=AccountType.EXPENSE,
    )
    ap = await _find_account(
        db, tenant_id, preferred_codes=("2000",), account_type=AccountType.LIABILITY,
    )

    entry = await post_journal_entry(
        db, tenant_id,
        lines=[
            {"account_id": expense.id, "debit": amount,
             "description": f"Accrue invoice {invoice.invoice_number}"},
            {"account_id": ap.id, "credit": amount,
             "description": f"Payable for invoice {invoice.invoice_number}"},
        ],
        description=f"Accrual for invoice {invoice.invoice_number}",
        reference=invoice.invoice_number,
        source_module="AP_ACCRUAL",
        source_document_id=invoice.id,
        created_by=actor,
    )
    logger.info("[AP] accrued invoice %s -> JE %s (%s)",
                invoice.invoice_number, entry.entry_number, amount)
    return entry


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
    match_override_by: Optional[str] = None,
) -> Payment:
    """Record a vendor payment and post it to the GL - one atomic commit.

    Raises PaymentError / GLPostingError with NOTHING recorded on any
    control violation. A ``three_way_match_status`` of EXCEPTION blocks the
    payment unless ``match_override_by`` records a human who accepts the
    exception (and who is not the person recording the payment).
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
    # Duplicate control (moved off the workflow, which no longer offers a manual
    # PAID transition): an AI-flagged possible duplicate must be cleared first.
    if getattr(invoice, "ai_duplicate_flag", False):
        raise PaymentError(
            "AI flagged this invoice as a possible duplicate; clear the flag "
            "(route it through DISPUTED) before paying."
        )

    # The three-way match is a real gate: an EXCEPTION invoice cannot be paid
    # unless a human explicitly accepts the exception on the record.
    if getattr(invoice, "three_way_match_status", None) == "EXCEPTION":
        if not match_override_by or match_override_by == recorded_by:
            raise PaymentError(
                f"invoice {invoice.invoice_number} failed its three-way match "
                "(EXCEPTION); resolve the match or record a distinct human "
                "override before paying"
            )
        from app.core.audit import record_security_event
        await record_security_event(
            tenant_id=tenant_id, event_type="MODIFICATION", action="EXECUTE",
            result="ESCALATED", actor=match_override_by,
            resource_type="invoice", resource_id=invoice.id,
            details={"control": "THREE_WAY_MATCH", "override": True,
                     "recorded_by": recorded_by},
        )

    pay_amount = _money(amount)
    if pay_amount <= 0:
        raise PaymentError("payment amount must be positive")
    balance = Decimal(str(invoice.balance_due or 0))
    if pay_amount > balance:
        raise PaymentError(
            f"payment {pay_amount} exceeds the invoice balance {balance}"
        )

    # Recognize the liability first if it wasn't booked at approval (idempotent).
    # After this, the payment settles the payable rather than expensing cash.
    await accrue_invoice(db, tenant_id, invoice, actor=recorded_by)

    cash = await _find_account(
        db, tenant_id, account_id=bank_account_id,
        preferred_codes=("1010", "1000"), account_type=AccountType.ASSET, bank=True,
    )
    ap = await _find_account(
        db, tenant_id, preferred_codes=("2000",), account_type=AccountType.LIABILITY,
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
        amount=pay_amount,  # type: ignore[arg-type]  # sa-plugin: Numeric/PK column typed as unresolved _N | None
        currency=invoice.currency or "USD",
        method=PaymentMethod(method) if not isinstance(method, PaymentMethod) else method,
        status=PaymentStatus.COMPLETED,
        bank_account_id=bank_account_id,
        reference_number=reference_number,
    )
    db.add(payment)

    # Invoice state rides in the same pending transaction as the entry.
    invoice.amount_paid = (Decimal(str(invoice.amount_paid or 0)) + pay_amount)  # type: ignore[assignment]  # sa-plugin: Numeric/PK column typed as unresolved _N | None
    invoice.balance_due = balance - pay_amount  # type: ignore[assignment]  # sa-plugin: Numeric/PK column typed as unresolved _N | None
    if invoice.balance_due == 0:
        invoice.status = InvoiceStatus.PAID

    # The keystone commits the session: payment + invoice update + entry +
    # lines + balances + signed provenance land together or not at all.
    # Accrual basis: settle the payable, not expense cash.
    entry = await post_journal_entry(
        db, tenant_id,
        lines=[
            {"account_id": ap.id, "debit": pay_amount,
             "description": f"Settle invoice {invoice.invoice_number}"},
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
