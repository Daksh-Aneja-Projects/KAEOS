"""
KAEOS Finance Domain — V1 API Router
Comprehensive CRUD and operational endpoints for all finance functions.
"""
from app.core.tenant import get_tenant_id, require_role
from app.core.audit import record_security_event
from fastapi import APIRouter, Depends, HTTPException
from typing import Optional
from datetime import date
from app.core.department_endpoints import get_or_404, make_department_workflow_router
from app.core.database import get_db
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func as sqlfunc

from app.finance.models.core import ChartOfAccount
from app.finance.models.accounts_payable import Vendor, Invoice, Payment, InvoiceStatus
from app.finance.models.accounts_receivable import Customer, CustomerInvoice, CustomerInvoiceStatus
from app.finance.models.budgeting import Budget, BudgetLine, Forecast, BudgetStatus
from app.finance.models.expense import ExpenseReport, ExpenseItem, ExpenseReportStatus
from app.finance.models.treasury import BankAccount, CashFlow
from app.finance.models.tax import TaxFiling, TaxRule
from app.finance.models.reporting import FinancialReport
from app.finance.models.audit import AuditFinding
from app.finance.models.compliance import FinanceComplianceRule, SOXControl

import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/finance", tags=["Finance"])


# ═══════════════════════════════════════════════════════════════════════
# Dashboard / Overview
# ═══════════════════════════════════════════════════════════════════════

@router.get("/dashboard")
async def finance_dashboard(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    """Aggregated finance dashboard KPIs."""
    # Vendors
    vendor_q = await db.execute(select(sqlfunc.count()).select_from(Vendor).where(Vendor.tenant_id == tenant_id))
    total_vendors = vendor_q.scalar() or 0

    # AP
    ap_q = await db.execute(
        select(sqlfunc.count(), sqlfunc.coalesce(sqlfunc.sum(Invoice.balance_due), 0))
        .select_from(Invoice).where(Invoice.tenant_id == tenant_id)
        .where(Invoice.status.in_([InvoiceStatus.PENDING_APPROVAL, InvoiceStatus.APPROVED, InvoiceStatus.OVERDUE]))
    )
    ap_row = ap_q.one()
    open_invoices, total_ap = int(ap_row[0] or 0), float(ap_row[1] or 0)

    # AR
    ar_q = await db.execute(
        select(sqlfunc.count(), sqlfunc.coalesce(sqlfunc.sum(CustomerInvoice.balance_due), 0))
        .select_from(CustomerInvoice).where(CustomerInvoice.tenant_id == tenant_id)
        .where(CustomerInvoice.status.in_([CustomerInvoiceStatus.SENT, CustomerInvoiceStatus.OVERDUE, CustomerInvoiceStatus.PARTIALLY_PAID]))
    )
    ar_row = ar_q.one()
    open_receivables, total_ar = int(ar_row[0] or 0), float(ar_row[1] or 0)

    # Bank balance
    bank_q = await db.execute(
        select(sqlfunc.coalesce(sqlfunc.sum(BankAccount.current_balance), 0))
        .select_from(BankAccount).where(BankAccount.tenant_id == tenant_id).where(BankAccount.is_active == True)
    )
    total_cash = float(bank_q.scalar() or 0)

    # Expense reports
    exp_q = await db.execute(
        select(sqlfunc.count()).select_from(ExpenseReport).where(ExpenseReport.tenant_id == tenant_id)
        .where(ExpenseReport.status == ExpenseReportStatus.PENDING_APPROVAL)
    )
    pending_expenses = exp_q.scalar() or 0

    # Budget
    budget_q = await db.execute(
        select(Budget).where(Budget.tenant_id == tenant_id).where(Budget.status == BudgetStatus.ACTIVE)
    )
    active_budgets = budget_q.scalars().all()

    # Audit findings
    finding_q = await db.execute(
        select(sqlfunc.count()).select_from(AuditFinding).where(AuditFinding.tenant_id == tenant_id)
        .where(AuditFinding.status.in_(["OPEN", "IN_PROGRESS"]))
    )
    open_findings = finding_q.scalar() or 0

    return {
        "total_cash_position": total_cash,
        "accounts_payable": {"open_invoices": open_invoices, "total_outstanding": total_ap},
        "accounts_receivable": {"open_receivables": open_receivables, "total_outstanding": total_ar},
        "total_vendors": total_vendors,
        "pending_expense_reports": pending_expenses,
        "active_budgets": len(active_budgets),
        "budget_variance_pct": active_budgets[0].variance_pct if active_budgets else None,
        "open_audit_findings": open_findings,
        "net_working_capital": total_cash + total_ar - total_ap,
    }


# ═══════════════════════════════════════════════════════════════════════
# Chart of Accounts
# ═══════════════════════════════════════════════════════════════════════

@router.get("/chart-of-accounts")
async def list_chart_of_accounts(tenant_id: str = Depends(get_tenant_id), account_type: Optional[str] = None, db: AsyncSession = Depends(get_db)):
    q = select(ChartOfAccount).where(ChartOfAccount.tenant_id == tenant_id)
    if account_type:
        q = q.where(ChartOfAccount.account_type == account_type)
    result = await db.execute(q.order_by(ChartOfAccount.account_code).limit(200))
    accounts = result.scalars().all()
    return [{"id": a.id, "code": a.account_code, "name": a.account_name, "type": a.account_type.value,
             "balance": float(a.current_balance or 0), "currency": a.currency, "is_active": a.is_active,
             "department": a.department, "cost_center": a.cost_center} for a in accounts]


# ═══════════════════════════════════════════════════════════════════════
# General Ledger — the posting keystone (real double entry)
# ═══════════════════════════════════════════════════════════════════════

from pydantic import BaseModel
from app.core.tenant import approver_identity


class JournalLineIn(BaseModel):
    account_id: Optional[str] = None
    account_code: Optional[str] = None
    debit: float = 0
    credit: float = 0
    description: Optional[str] = None
    department: Optional[str] = None
    cost_center: Optional[str] = None


class JournalEntryIn(BaseModel):
    description: str
    lines: list[JournalLineIn]
    reference: Optional[str] = None
    source_module: str = "MANUAL"
    source_document_id: Optional[str] = None
    # Maker-checker four-eyes: the preparer (maker). The authenticated poster is
    # the approver; the two must be distinct, attributable identities.
    prepared_by: Optional[str] = None


# Source modules reserved for AUTOMATED postings (accruals, payments, matching).
# Those callers reach post_journal_entry directly at the service layer and never
# transit this HTTP route, so a hand-posted system source here is a four-eyes
# dodge (masquerading a manual JE as an automated one) and is refused.
_SYSTEM_JE_SOURCES = {"AP", "AP_ACCRUAL", "AR", "PAYROLL", "PAYMENT", "THREE_WAY_MATCH"}


def _entry_dict(e) -> dict:
    return {
        "id": e.id, "entry_number": e.entry_number,
        "entry_date": e.entry_date.isoformat() if e.entry_date else None,
        "posting_date": e.posting_date.isoformat() if e.posting_date else None,
        "description": e.description, "reference": e.reference,
        "source_module": e.source_module, "status": getattr(e.status, "value", e.status),
        "total_debit": float(e.total_debit or 0), "total_credit": float(e.total_credit or 0),
        "created_by": e.created_by, "fiscal_year": e.fiscal_year,
        "fiscal_period": e.fiscal_period,
    }


@router.post("/gl/journal-entries")
async def post_gl_entry(body: JournalEntryIn, tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db)):
    """Post a balanced journal entry - the only write path into the GL.

    Fail-closed double entry: unbalanced, zero-amount, or unknown-account
    entries are refused with nothing posted. Balances move atomically with
    the entry, and the posting lands in the signed provenance ledger."""
    from app.compliance.registry import run_checks
    from app.core.tenant import approver_identity
    from app.finance.services.gl import GLPostingError, post_journal_entry
    tenant_id = tenant["tenant_id"]
    poster = approver_identity(tenant)
    src = (body.source_module or "MANUAL").strip().upper()
    if src in _SYSTEM_JE_SOURCES:
        raise HTTPException(403, detail=(
            f"source_module '{src}' is reserved for automated postings and cannot "
            "be hand-posted; use MANUAL or ADJUSTING for a manual journal entry."))
    # SOX 302/404 maker-checker on manual JEs: the preparer (maker) and the
    # posting operator (approver) must be two distinct, attributable identities.
    # Fail-closed via the finance SOX checker - a self-prepared or unattributable
    # manual JE is BLOCKED (mirrors the operations four-eyes SoD gate).
    maker = body.prepared_by
    verdict = run_checks(["SOX"], {
        "is_financial": True, "has_human_approver": poster,
        "maker": maker, "approver": poster,
    })
    if not verdict["verified"]:
        raise HTTPException(403, detail={
            "error": "segregation_of_duties",
            "message": ("A manual journal entry needs maker-checker four-eyes: set "
                        "prepared_by to a distinct, attributable preparer; the posting "
                        "operator approves. A self-prepared or unattributable JE is blocked."),
            "blocking": verdict["blocking"],
        })
    try:
        entry = await post_journal_entry(
            db, tenant_id,
            lines=[l.model_dump() for l in body.lines],
            description=body.description,
            reference=body.reference,
            source_module=body.source_module,
            source_document_id=body.source_document_id,
            created_by=maker,
            approved_by=poster,
        )
    except GLPostingError as e:
        raise HTTPException(400, str(e))
    await record_security_event(
        tenant_id=tenant_id, event_type="MODIFICATION", action="WRITE",
        actor=approver_identity(tenant), actor_role=tenant.get("role"),
        resource_type="journal_entry", resource_id=entry.id,
        details={"entry_number": entry.entry_number,
                 "total": float(entry.total_debit or 0),
                 "prepared_by": maker, "approved_by": poster},
    )
    return _entry_dict(entry)


@router.post("/gl/journal-entries/{entry_id}/reverse")
async def reverse_gl_entry(entry_id: str, tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db)):
    """Reverse a POSTED entry with a mirror entry (append-only correction)."""
    from app.core.tenant import approver_identity
    from app.finance.services.gl import GLPostingError, reverse_journal_entry
    tenant_id = tenant["tenant_id"]
    try:
        mirror = await reverse_journal_entry(
            db, tenant_id, entry_id, actor=approver_identity(tenant))
    except GLPostingError as e:
        raise HTTPException(400, str(e))
    return _entry_dict(mirror)


@router.get("/gl/journal-entries")
async def list_gl_entries(
    limit: int = 50, tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)
):
    from app.finance.models.core import JournalEntry
    rows = (await db.execute(
        select(JournalEntry).where(JournalEntry.tenant_id == tenant_id)
        .order_by(JournalEntry.created_at.desc()).limit(max(1, min(200, limit)))
    )).scalars().all()
    return [_entry_dict(e) for e in rows]


@router.get("/gl/trial-balance")
async def get_trial_balance(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    """Trial balance derived from POSTED journal lines (the ledger is the
    source of truth; cached balances are cross-checked and drift reported)."""
    from app.finance.services.gl import trial_balance
    return await trial_balance(db, tenant_id)


@router.get("/gl/income-statement")
async def get_income_statement(
    period_start: Optional[date] = None, period_end: Optional[date] = None,
    tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db),
):
    """Profit & loss from the ledger. Inception-to-date by default; pass
    period_start/period_end (YYYY-MM-DD) to bound the reporting window."""
    from app.finance.services.gl import income_statement
    return await income_statement(db, tenant_id, period_start=period_start, period_end=period_end)


@router.get("/gl/balance-sheet")
async def get_balance_sheet(
    as_of: Optional[date] = None,
    tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db),
):
    """Balance sheet from the ledger as of a date (inception-to-date by
    default). Current-period earnings close into equity so it always balances."""
    from app.finance.services.gl import balance_sheet
    return await balance_sheet(db, tenant_id, as_of=as_of)


@router.get("/gl/cash-flow-statement")
async def get_cash_flow_statement(
    period_start: Optional[date] = None, period_end: Optional[date] = None,
    tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db),
):
    """Net change in cash/bank accounts over a window, derived from POSTED
    journal lines (not the persisted CashFlow rows). Pass period_start/period_end
    (YYYY-MM-DD) to bound the window; omit for inception-to-date."""
    from app.finance.services.gl import cash_flow_statement
    return await cash_flow_statement(db, tenant_id, period_start=period_start, period_end=period_end)


@router.get("/aging")
async def get_aging_report(
    side: str = "both", as_of: Optional[date] = None,
    tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db),
):
    """AR/AP aging: open invoice balances bucketed by days past due_date
    (current / 1-30 / 31-60 / 61-90 / 90+). side = ar | ap | both."""
    if side.lower() not in ("ar", "ap", "both"):
        raise HTTPException(400, "side must be one of: ar, ap, both")
    from app.finance.services.gl import aging_report
    return await aging_report(db, tenant_id, side=side, as_of=as_of)


@router.get("/gl/periods")
async def get_fiscal_periods(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    """Closed/reopened fiscal periods. Periods without a row are OPEN."""
    from app.finance.services.gl import list_periods
    return await list_periods(db, tenant_id)


class PeriodActionIn(BaseModel):
    fiscal_year: int
    fiscal_period: int
    note: Optional[str] = None


@router.post("/gl/periods/close")
async def close_fiscal_period(
    body: PeriodActionIn,
    tenant: dict = Depends(require_role("admin")), db: AsyncSession = Depends(get_db),
):
    """Close a fiscal period - back-dated postings into it are then refused.
    Admin-only: closing a period is a reporting control."""
    from app.core.tenant import approver_identity
    from app.finance.services.gl import GLPostingError, set_period_status
    tenant_id = tenant["tenant_id"]
    try:
        result = await set_period_status(
            db, tenant_id, body.fiscal_year, body.fiscal_period,
            close=True, actor=approver_identity(tenant), note=body.note)
    except GLPostingError as e:
        raise HTTPException(400, str(e))
    await record_security_event(
        tenant_id=tenant_id, event_type="MODIFICATION", action="WRITE",
        actor=approver_identity(tenant), actor_role=tenant.get("role"),
        resource_type="fiscal_period", resource_id=f"{body.fiscal_year}-{body.fiscal_period:02d}",
        details={"status": "CLOSED"},
    )
    return result


@router.post("/gl/periods/reopen")
async def reopen_fiscal_period(
    body: PeriodActionIn,
    tenant: dict = Depends(require_role("admin")), db: AsyncSession = Depends(get_db),
):
    """Reopen a closed fiscal period (admin-only) so corrections can post."""
    from app.core.tenant import approver_identity
    from app.finance.services.gl import GLPostingError, set_period_status
    tenant_id = tenant["tenant_id"]
    try:
        result = await set_period_status(
            db, tenant_id, body.fiscal_year, body.fiscal_period,
            close=False, actor=approver_identity(tenant), note=body.note)
    except GLPostingError as e:
        raise HTTPException(400, str(e))
    await record_security_event(
        tenant_id=tenant_id, event_type="MODIFICATION", action="WRITE",
        actor=approver_identity(tenant), actor_role=tenant.get("role"),
        resource_type="fiscal_period", resource_id=f"{body.fiscal_year}-{body.fiscal_period:02d}",
        details={"status": "OPEN"},
    )
    return result


# ═══════════════════════════════════════════════════════════════════════
# Accounts Payable
# ═══════════════════════════════════════════════════════════════════════

@router.get("/vendors")
async def list_vendors(tenant_id: str = Depends(get_tenant_id), status: Optional[str] = None, db: AsyncSession = Depends(get_db)):
    q = select(Vendor).where(Vendor.tenant_id == tenant_id)
    if status:
        q = q.where(Vendor.status == status)
    result = await db.execute(q.limit(200))
    vendors = result.scalars().all()
    return [{"id": v.id, "code": v.vendor_code, "name": v.name, "status": v.status.value,
             "payment_terms": v.payment_terms_days, "spend_ytd": float(v.total_spend_ytd or 0),
             "performance_score": v.performance_score, "risk_level": v.risk_level} for v in vendors]

@router.get("/vendors/{vendor_id}")
async def get_vendor(vendor_id: str, tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    q = await db.execute(select(Vendor).where(Vendor.id == vendor_id, Vendor.tenant_id == tenant_id))
    v = q.scalar_one_or_none()
    if not v:
        # 404 (not 403) for another tenant's row: 403 would confirm the id exists.
        raise HTTPException(404, "Vendor not found")
    return {"id": v.id, "code": v.vendor_code, "name": v.name, "legal_name": v.legal_name,
            "email": v.email, "phone": v.phone, "status": v.status.value, "payment_terms": v.payment_terms_days,
            "currency": v.currency, "w9_on_file": v.w9_on_file, "risk_level": v.risk_level,
            "spend_ytd": float(v.total_spend_ytd or 0), "invoices_ytd": v.total_invoices_ytd,
            "performance_score": v.performance_score, "address": {"line1": v.address_line1, "city": v.city, "state": v.state, "country": v.country}}

@router.get("/invoices")
async def list_invoices(tenant_id: str = Depends(get_tenant_id), status: Optional[str] = None, vendor_id: Optional[str] = None, db: AsyncSession = Depends(get_db)):
    q = select(Invoice).where(Invoice.tenant_id == tenant_id)
    if status:
        q = q.where(Invoice.status == status)
    if vendor_id:
        q = q.where(Invoice.vendor_id == vendor_id)
    result = await db.execute(q.order_by(Invoice.due_date).limit(200))
    invoices = result.scalars().all()
    return [{"id": i.id, "number": i.invoice_number, "vendor_id": i.vendor_id, "status": i.status.value,
             "total": float(i.total_amount), "balance": float(i.balance_due), "due_date": str(i.due_date),
             "po_number": i.po_number, "three_way_match": i.three_way_match_status, "ai_duplicate": i.ai_duplicate_flag} for i in invoices]

class PaymentIn(BaseModel):
    invoice_id: str
    amount: float
    method: str = "ACH"
    reference_number: Optional[str] = None
    bank_account_id: Optional[str] = None


@router.post("/payments")
async def record_payment(body: PaymentIn, tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db)):
    """Record a vendor payment - the first P2P money event wired end to end.

    Controls: the invoice must be APPROVED with a recorded approver, the payer
    may not be that approver (four-eyes), overpayment is refused, and the
    payment posts through the GL keystone atomically with the Payment row and
    invoice balance (accrual: DR accounts-payable / CR cash, accruing the
    invoice first if it was not booked at approval)."""
    from app.core.tenant import approver_identity
    from app.finance.services.gl import GLPostingError
    from app.finance.services.payments import PaymentError, record_vendor_payment
    tenant_id = tenant["tenant_id"]
    try:
        payment = await record_vendor_payment(
            db, tenant_id,
            invoice_id=body.invoice_id,
            amount=body.amount,
            method=body.method,
            reference_number=body.reference_number,
            bank_account_id=body.bank_account_id,
            recorded_by=approver_identity(tenant),
        )
    except PaymentError as e:
        code = 403 if str(e).startswith("Four-eyes") else 400
        raise HTTPException(code, str(e))
    except GLPostingError as e:
        raise HTTPException(400, str(e))
    await record_security_event(
        tenant_id=tenant_id, event_type="MODIFICATION", action="WRITE",
        actor=approver_identity(tenant), actor_role=tenant.get("role"),
        resource_type="payment", resource_id=payment.id,
        details={"payment_number": payment.payment_number,
                 "amount": float(payment.amount or 0)},
    )
    return {"id": payment.id, "payment_number": payment.payment_number,
            "amount": float(payment.amount or 0),
            "status": payment.status.value,
            "journal_entry_id": payment.journal_entry_id}


@router.get("/payments")
async def list_payments(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    q = await db.execute(select(Payment).where(Payment.tenant_id == tenant_id).order_by(Payment.payment_date.desc()).limit(200))
    payments = q.scalars().all()
    return [{"id": p.id, "number": p.payment_number, "vendor_id": p.vendor_id, "amount": float(p.amount),
             "method": p.method.value, "status": p.status.value, "date": str(p.payment_date)} for p in payments]


# ═══════════════════════════════════════════════════════════════════════
# Accounts Receivable
# ═══════════════════════════════════════════════════════════════════════

@router.get("/customers")
async def list_customers(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    q = await db.execute(select(Customer).where(Customer.tenant_id == tenant_id).limit(200))
    customers = q.scalars().all()
    return [{"id": c.id, "code": c.customer_code, "name": c.name, "status": c.status.value,
             "outstanding": float(c.total_outstanding or 0), "revenue_ytd": float(c.total_revenue_ytd or 0),
             "dso": c.days_sales_outstanding, "churn_risk": c.ai_churn_risk,
             "aging": {"current": float(c.aging_current or 0), "30": float(c.aging_30 or 0),
                       "60": float(c.aging_60 or 0), "90": float(c.aging_90 or 0), "over_90": float(c.aging_over_90 or 0)}}
            for c in customers]

@router.get("/receivables")
async def list_receivables(tenant_id: str = Depends(get_tenant_id), status: Optional[str] = None, db: AsyncSession = Depends(get_db)):
    q = select(CustomerInvoice).where(CustomerInvoice.tenant_id == tenant_id)
    if status:
        q = q.where(CustomerInvoice.status == status)
    result = await db.execute(q.order_by(CustomerInvoice.due_date).limit(200))
    invoices = result.scalars().all()
    return [{"id": i.id, "number": i.invoice_number, "customer_id": i.customer_id, "status": i.status.value,
             "total": float(i.total_amount), "balance": float(i.balance_due), "due_date": str(i.due_date),
             "dunning_level": i.dunning_level} for i in invoices]


# ═══════════════════════════════════════════════════════════════════════
# Budgets & Forecasts
# ═══════════════════════════════════════════════════════════════════════

@router.get("/budgets")
async def list_budgets(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    q = await db.execute(select(Budget).where(Budget.tenant_id == tenant_id).limit(200))
    budgets = q.scalars().all()
    return [{"id": b.id, "name": b.name, "type": b.budget_type, "year": b.fiscal_year, "status": b.status.value,
             "planned": float(b.total_planned), "actual": float(b.total_actual), "variance": float(b.total_variance),
             "variance_pct": b.variance_pct, "department": b.department} for b in budgets]

@router.get("/budgets/{budget_id}/lines")
async def get_budget_lines(budget_id: str, tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    # IDOR: this took no tenant at all - any caller who knew (or guessed) a
    # budget id got another company's financial lines back.
    q = await db.execute(
        select(BudgetLine)
        .where(BudgetLine.tenant_id == tenant_id, BudgetLine.budget_id == budget_id)
        .order_by(BudgetLine.period)
        .limit(200)
    )
    lines = q.scalars().all()
    return [{"id": l.id, "category": l.category, "period": l.period, "label": l.period_label,
             "planned": float(l.planned_amount), "actual": float(l.actual_amount),
             "committed": float(l.committed_amount), "variance": float(l.variance)} for l in lines]

@router.get("/forecasts")
async def list_forecasts(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    q = await db.execute(select(Forecast).where(Forecast.tenant_id == tenant_id).limit(200))
    forecasts = q.scalars().all()
    return [{"id": f.id, "name": f.forecast_name, "type": f.forecast_type, "scenario": f.scenario,
             "total": float(f.total_forecast), "confidence": f.confidence_score,
             "period": f"{f.period_start} to {f.period_end}"} for f in forecasts]


# ═══════════════════════════════════════════════════════════════════════
# Expense Management
# ═══════════════════════════════════════════════════════════════════════

@router.get("/expense-reports")
async def list_expense_reports(tenant_id: str = Depends(get_tenant_id), status: Optional[str] = None, db: AsyncSession = Depends(get_db)):
    q = select(ExpenseReport).where(ExpenseReport.tenant_id == tenant_id)
    if status:
        q = q.where(ExpenseReport.status == status)
    result = await db.execute(q.order_by(ExpenseReport.created_at.desc()).limit(200))
    reports = result.scalars().all()
    return [{"id": r.id, "number": r.report_number, "title": r.title, "employee_id": r.employee_id,
             "status": r.status.value, "total": float(r.total_amount), "approved": float(r.approved_amount or 0),
             "compliance_score": r.ai_compliance_score, "violations": len(r.ai_policy_violations or [])} for r in reports]

@router.get("/expense-reports/{report_id}/items")
async def get_expense_items(report_id: str, tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    q = await db.execute(
        select(ExpenseItem)
        .where(ExpenseItem.tenant_id == tenant_id, ExpenseItem.report_id == report_id)
        .order_by(ExpenseItem.line_number)
        .limit(200)
    )
    items = q.scalars().all()
    return [{"id": i.id, "date": str(i.expense_date), "category": i.category.value, "description": i.description,
             "merchant": i.merchant, "amount": float(i.amount), "has_receipt": bool(i.receipt_path),
             "within_policy": i.is_within_policy, "billable": i.is_billable} for i in items]


# ═══════════════════════════════════════════════════════════════════════
# Treasury / Cash Management
# ═══════════════════════════════════════════════════════════════════════

@router.get("/bank-accounts")
async def list_bank_accounts(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    q = await db.execute(select(BankAccount).where(BankAccount.tenant_id == tenant_id).limit(200))
    accounts = q.scalars().all()
    return [{"id": a.id, "name": a.account_name, "bank": a.bank_name, "masked_number": a.account_number_masked,
             "classification": a.classification.value, "balance": float(a.current_balance or 0),
             "available": float(a.available_balance or 0), "currency": a.currency,
             "last_reconciled": str(a.last_reconciled_date) if a.last_reconciled_date else None} for a in accounts]

@router.get("/cash-flow")
async def get_cash_flow(tenant_id: str = Depends(get_tenant_id), fiscal_year: Optional[int] = None, db: AsyncSession = Depends(get_db)):
    q = select(CashFlow).where(CashFlow.tenant_id == tenant_id)
    if fiscal_year:
        q = q.where(CashFlow.fiscal_year == fiscal_year)
    result = await db.execute(q.order_by(CashFlow.flow_date.desc()).limit(200))
    flows = result.scalars().all()
    return [{"id": f.id, "date": str(f.flow_date), "type": f.flow_type.value, "category": f.category,
             "amount": float(f.amount), "is_forecast": f.is_forecast, "source": f.source_module} for f in flows]


# ═══════════════════════════════════════════════════════════════════════
# Tax
# ═══════════════════════════════════════════════════════════════════════

@router.get("/tax/filings")
async def list_tax_filings(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    q = await db.execute(select(TaxFiling).where(TaxFiling.tenant_id == tenant_id).order_by(TaxFiling.due_date).limit(200))
    filings = q.scalars().all()
    return [{"id": f.id, "type": f.filing_type, "jurisdiction": f.jurisdiction, "period": f.period,
             "status": f.status.value, "liability": float(f.tax_liability or 0), "paid": float(f.tax_paid or 0),
             "due_date": str(f.due_date), "form": f.form_number} for f in filings]

@router.get("/tax/rules")
async def list_tax_rules(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    q = await db.execute(select(TaxRule).where(TaxRule.tenant_id == tenant_id).where(TaxRule.is_active == True).limit(200))
    rules = q.scalars().all()
    return [{"id": r.id, "name": r.name, "type": r.tax_type, "jurisdiction": r.jurisdiction,
             "rate": r.rate, "progressive": r.is_progressive} for r in rules]


# ═══════════════════════════════════════════════════════════════════════
# Financial Reports
# ═══════════════════════════════════════════════════════════════════════

@router.get("/reports")
async def list_reports(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    q = await db.execute(select(FinancialReport).where(FinancialReport.tenant_id == tenant_id).order_by(FinancialReport.created_at.desc()).limit(200))
    reports = q.scalars().all()
    return [{"id": r.id, "type": r.report_type.value, "title": r.title, "status": r.status.value,
             "period": f"{r.period_start} to {r.period_end}", "ai_anomalies": len(r.ai_anomalies or []),
             "generated_at": str(r.generated_at) if r.generated_at else None} for r in reports]


# ═══════════════════════════════════════════════════════════════════════
# Audit & Compliance
# ═══════════════════════════════════════════════════════════════════════

@router.get("/audit/findings")
async def list_audit_findings(tenant_id: str = Depends(get_tenant_id), status: Optional[str] = None, db: AsyncSession = Depends(get_db)):
    q = select(AuditFinding).where(AuditFinding.tenant_id == tenant_id)
    if status:
        q = q.where(AuditFinding.status == status)
    result = await db.execute(q.limit(200))
    findings = result.scalars().all()
    return [{"id": f.id, "number": f.finding_number, "title": f.title, "severity": f.severity.value,
             "status": f.status.value, "area": f.area, "impact": float(f.financial_impact or 0),
             "owner": f.remediation_owner, "ai_detected": f.ai_detected} for f in findings]

@router.get("/sox-controls")
async def list_sox_controls(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    q = await db.execute(select(SOXControl).where(SOXControl.tenant_id == tenant_id).limit(200))
    controls = q.scalars().all()
    return [{"id": c.id, "code": c.control_id_code, "name": c.name, "type": c.control_type,
             "frequency": c.frequency, "nature": c.nature, "area": c.area, "status": c.status.value,
             "risk_level": c.risk_level, "ai_score": c.ai_effectiveness_score} for c in controls]

@router.get("/compliance-rules")
async def list_compliance_rules(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    q = await db.execute(select(FinanceComplianceRule).where(FinanceComplianceRule.tenant_id == tenant_id).where(FinanceComplianceRule.is_active == True).limit(200))
    rules = q.scalars().all()
    return [{"id": r.id, "regulation": r.regulation, "section": r.section, "name": r.name,
             "severity": r.severity, "is_blocking": r.is_blocking, "applies_to": r.applies_to} for r in rules]


# ═══════════════════════════════════════════════════════════════════════
# Agent Execution Triggers
# ═══════════════════════════════════════════════════════════════════════

@router.post("/invoices/{invoice_id}/match")
async def run_ap_agent(invoice_id: str, tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db)):
    """Triggers the Accounts Payable agent to perform 3-way matching."""
    tenant_id = tenant["tenant_id"]
    from app.finance.agents.ap_agent import APAgent
    agent = APAgent()
    try:
        result = await agent.process_invoice(db, invoice_id, tenant_id)
        await record_security_event(
            tenant_id=tenant_id, event_type="MODIFICATION", action="EXECUTE",
            actor=approver_identity(tenant), actor_role=tenant.get("role"),
            resource_type="invoice", resource_id=invoice_id,
        )
        return result
    except ValueError as e:
        # Unknown / other-tenant id, like the nine sibling departments -> 404
        # (never 403, so another tenant's id is not confirmed to exist).
        raise HTTPException(404, detail=str(e)) from e
    except Exception as e:
        logger.exception("%s failed", __name__)
        raise HTTPException(500, detail="Internal error - see server logs") from e


@router.post("/receivables/{invoice_id}/dunning")
async def run_ar_agent(invoice_id: str, tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db)):
    """Triggers the Accounts Receivable agent to generate dunning letters."""
    tenant_id = tenant["tenant_id"]
    from app.finance.agents.ar_agent import ARAgent
    agent = ARAgent()
    try:
        result = await agent.generate_dunning(db, invoice_id, tenant_id)
        # Ensure the letter body is passed as 'letter' as expected by the frontend
        result["letter"] = f"Subject: {result.get('subject')}\n\n{result.get('body')}"
        await record_security_event(
            tenant_id=tenant_id, event_type="MODIFICATION", action="EXECUTE",
            actor=approver_identity(tenant), actor_role=tenant.get("role"),
            resource_type="receivable", resource_id=invoice_id,
        )
        return result
    except ValueError as e:
        raise HTTPException(404, detail=str(e)) from e
    except HTTPException:
        raise  # a deliberate status is not a 500
    except Exception as e:
        logger.exception("%s failed", __name__)
        raise HTTPException(500, detail="Internal error - see server logs") from e


# ═══════════════════════════════════════════════════════════════════════
# Analytics & Workflow Layer (shared engine: app.core.workflow)
# ═══════════════════════════════════════════════════════════════════════
from app.core.workflow import (  # noqa: E402
    BulkTransitionRequest, TransitionRequest, apply_bulk_transition,
    apply_transition,
)
from app.finance.services.analytics import finance_analytics  # noqa: E402
from app.finance.services.workflows import SPECS as WORKFLOW_SPECS  # noqa: E402


@router.get("/analytics")
async def get_finance_analytics(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    """Computed KPIs, distributions and insights for the finance cockpit."""
    return await finance_analytics(db, tenant_id)


# Generated from the shared factory in app/core/department_endpoints.py.
# Endpoint names and docstrings are the hand-written originals, so the
# operationIds and descriptions in the OpenAPI schema are unchanged.
router.include_router(make_department_workflow_router(
    "finance", WORKFLOW_SPECS,
    workflows_doc='Declared state machines — the frontend renders transition actions from this.',
    events_doc='Tenant-scoped transition audit trail for finance entities.',
))


async def _apply_invoice_ledger_effects(
    db: AsyncSession, tenant: dict, invoice_id: str, result: dict,
) -> None:
    """Post the accrual on APPROVED / reverse it on VOID for one invoice,
    annotating ``result`` in place. Shared by the single- and bulk-transition
    paths so the GL stays in sync whichever endpoint drove the state change
    (bulk approve/void used to skip this, inflating AP and the P&L). Never
    raises: a COA gap is surfaced on the result, not fatal, exactly as the
    single-invoice path always behaved."""
    to_state = result.get("to_state")
    tenant_id = tenant["tenant_id"]
    if to_state == InvoiceStatus.APPROVED.value:
        from app.core.tenant import approver_identity
        from app.finance.services.gl import GLPostingError
        from app.finance.services.payments import PaymentError, accrue_invoice
        invoice = (await db.execute(select(Invoice).where(
            Invoice.id == invoice_id, Invoice.tenant_id == tenant_id))).scalar_one_or_none()
        if invoice is not None:
            try:
                entry = await accrue_invoice(db, tenant_id, invoice,
                                             actor=approver_identity(tenant))
                if entry is not None:
                    result["accrual_entry"] = entry.entry_number
            except (GLPostingError, PaymentError) as e:
                # The approval is a valid state change and already committed;
                # accrual will be retried (idempotently) at payment time. Surface
                # the COA gap (a missing expense/AP account raises PaymentError)
                # instead of failing the approval or hiding it.
                logger.warning("[AP] accrual on approval of %s failed: %s", invoice_id, e)
                result["accrual_warning"] = str(e)
    elif to_state == InvoiceStatus.VOIDED.value:
        # Voiding an accrued invoice must UNWIND its AP_ACCRUAL entry, else the
        # P&L overstates expense and the balance sheet overstates AP for an invoice
        # that no longer exists. Reverse the accrual (append-only mirror). Skip if
        # the invoice already took a payment - that needs a manual reconciliation.
        from decimal import Decimal
        from app.core.tenant import approver_identity
        from app.finance.models.core import JournalEntry, JournalEntryStatus
        from app.finance.services.gl import GLPostingError, reverse_journal_entry
        invoice = (await db.execute(select(Invoice).where(
            Invoice.id == invoice_id, Invoice.tenant_id == tenant_id))).scalar_one_or_none()
        accrual = (await db.execute(select(JournalEntry).where(
            JournalEntry.tenant_id == tenant_id,
            JournalEntry.source_module == "AP_ACCRUAL",
            JournalEntry.source_document_id == invoice_id,
            JournalEntry.status == JournalEntryStatus.POSTED,
        ))).scalar_one_or_none()
        if accrual is not None and invoice is not None:
            if Decimal(str(invoice.amount_paid or 0)) != 0:
                result["reversal_warning"] = ("invoice has payments; accrual not "
                    "auto-reversed - reconcile the void manually")
            else:
                try:
                    mirror = await reverse_journal_entry(
                        db, tenant_id, accrual.id, actor=approver_identity(tenant))
                    result["accrual_reversed"] = mirror.entry_number
                except GLPostingError as e:
                    logger.warning("[AP] accrual reversal on void of %s failed: %s", invoice_id, e)
                    result["reversal_warning"] = str(e)


@router.post("/invoices/{invoice_id}/transition")
async def transition_invoice(
    invoice_id: str, body: TransitionRequest,
    tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db),
):
    """Guarded AP invoice lifecycle action (submit, approve, dispute, pay, void).

    Approving an invoice accrues it: DR expense / CR accounts-payable posts to
    the GL (idempotent) so the P&L and balance sheet reflect the new liability.
    """
    result = await apply_transition(db, WORKFLOW_SPECS["invoice"], invoice_id,
                                    body.to_state, tenant, note=body.note)
    await _apply_invoice_ledger_effects(db, tenant, invoice_id, result)
    return result


@router.post("/expense-reports/{report_id}/transition")
async def transition_expense_report(
    report_id: str, body: TransitionRequest,
    tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db),
):
    """Guarded expense report lifecycle action (submit, approve, reject, reimburse)."""
    return await apply_transition(db, WORKFLOW_SPECS["expense_report"], report_id,
                                  body.to_state, tenant, note=body.note)

# ═══════════════════════════════════════════════════════════════════════
# Entity Creation
# ═══════════════════════════════════════════════════════════════════════
import uuid as _uuid_mod  # noqa: E402
from datetime import date as _date  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402


class ExpenseReportCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=128)
    employee_id: str
    total_amount: float = Field(..., gt=0)
    description: Optional[str] = None
    department: Optional[str] = Field(None, max_length=64)


@router.post("/expense-reports", status_code=201)
async def create_expense_report(
    body: ExpenseReportCreate,
    tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db),
):
    """File an expense report (starts DRAFT; submit/approve via /transition)."""
    tenant_id = tenant["tenant_id"]
    rep = ExpenseReport(
        tenant_id=tenant_id,
        report_number=f"EXP-{_uuid_mod.uuid4().hex[:8].upper()}",
        title=body.title, employee_id=body.employee_id,
        total_amount=body.total_amount, description=body.description,
        department=body.department,
    )
    db.add(rep)
    await db.commit()
    await db.refresh(rep)
    await record_security_event(
        tenant_id=tenant_id, event_type="MODIFICATION", action="WRITE",
        actor=approver_identity(tenant), actor_role=tenant.get("role"),
        resource_type="expense_report", resource_id=rep.id,
    )
    return {"id": rep.id, "number": rep.report_number, "title": rep.title,
            "status": rep.status.value if hasattr(rep.status, "value") else str(rep.status),
            "total": float(rep.total_amount or 0)}


class InvoiceCreate(BaseModel):
    vendor_id: str
    invoice_number: Optional[str] = Field(None, max_length=64)
    invoice_date: _date
    due_date: _date
    subtotal: float = Field(..., gt=0)
    tax_amount: float = Field(0, ge=0)
    po_number: Optional[str] = Field(None, max_length=64)


def _norm_vendor_name(s: Optional[str]) -> str:
    """Casefold + strip non-alphanumerics so 'Acme, Inc.' == 'Acme Inc' and
    'L.L.C.' == 'LLC'. Used only to reconcile a finance vendor to a PO's
    denormalized vendor_name when the PO has no backfilled vendor_id."""
    return "".join(c for c in (s or "").lower() if c.isalnum())


@router.post("/invoices", status_code=201)
async def create_invoice(
    body: InvoiceCreate,
    tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db),
):
    """Register an AP invoice (starts DRAFT; approval/payment via /transition)."""
    tenant_id = tenant["tenant_id"]
    vendor = await get_or_404(db, Vendor, body.vendor_id, tenant_id, detail="Vendor not found")
    total = body.subtotal + body.tax_amount
    # Resolve the entered PO reference to the real ops PO so the 3-way match
    # can run off the FK, not a free-text string. Unknown PO -> NULL, no error.
    purchase_order_id = None
    if body.po_number:
        from app.operations.models.procurement import PurchaseOrder
        po_row = (await db.execute(select(
            PurchaseOrder.id, PurchaseOrder.vendor_id, PurchaseOrder.vendor_name
        ).where(
            PurchaseOrder.po_number == body.po_number,
            PurchaseOrder.tenant_id == tenant_id))).first()
        if po_row is not None:
            po_pk, po_vendor_id, po_vendor_name = po_row
            # Vendor-identity leg: without it, an invoice for vendor A can cite
            # vendor B's PO and pass the qty/price 3-way match against the wrong
            # order. The ops PO.vendor_id and Invoice.vendor_id share the
            # fin_vendors id space, so a direct id check reconciles them; fall
            # back to a normalized name match for a PO not yet backfilled to a
            # vendor_id. A real mismatch is refused, not silently mis-linked.
            if po_vendor_id is not None:
                reconciled = po_vendor_id == body.vendor_id
            else:
                reconciled = _norm_vendor_name(po_vendor_name) == _norm_vendor_name(vendor.name)
            if not reconciled:
                raise HTTPException(422, detail=(
                    f"Purchase order {body.po_number} belongs to a different "
                    "vendor; an invoice can only reference its own vendor's "
                    "purchase order."))
            purchase_order_id = po_pk
    inv = Invoice(
        tenant_id=tenant_id, vendor_id=body.vendor_id,
        invoice_number=body.invoice_number or f"INV-{_uuid_mod.uuid4().hex[:8].upper()}",
        invoice_date=body.invoice_date, due_date=body.due_date,
        subtotal=body.subtotal, tax_amount=body.tax_amount,
        total_amount=total, balance_due=total, po_number=body.po_number,
        purchase_order_id=purchase_order_id,
    )
    db.add(inv)
    await db.commit()
    await db.refresh(inv)
    await record_security_event(
        tenant_id=tenant_id, event_type="MODIFICATION", action="WRITE",
        actor=approver_identity(tenant), actor_role=tenant.get("role"),
        resource_type="invoice", resource_id=inv.id,
    )
    return {"id": inv.id, "number": inv.invoice_number,
            "status": inv.status.value if hasattr(inv.status, "value") else str(inv.status),
            "total": float(inv.total_amount), "balance": float(inv.balance_due)}


@router.post("/workflows/{entity_type}/bulk-transition")
async def bulk_transition_finance(
    entity_type: str, body: BulkTransitionRequest,
    tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db),
):
    """Apply one transition to up to 200 finance entities; per-id outcomes."""
    spec = WORKFLOW_SPECS.get(entity_type)
    if not spec:
        raise HTTPException(404, detail=f"Unknown workflow entity '{entity_type}'. Known: {sorted(WORKFLOW_SPECS)}")
    outcome = await apply_bulk_transition(db, spec, body.ids, body.to_state, tenant, note=body.note)
    # Bulk transitions ran through the shared engine, which does NOT post the
    # invoice accrual / void-reversal that the single-invoice endpoint runs -
    # so a bulk approve/void would silently desync the ledger. Re-run the same
    # per-invoice side-effect for each succeeded id so both paths post identically.
    if entity_type == "invoice":
        for row in outcome["results"]:
            if row.get("ok"):
                await _apply_invoice_ledger_effects(db, tenant, row["id"], row)
    return outcome
