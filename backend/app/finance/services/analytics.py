"""
KAEOS Finance — Analytics Service
Real SQL aggregates over tenant data: AP aging, status mix, expense
compliance, cash by classification, top vendors. Returns the shared
domain-analytics shape rendered by the frontend DomainAnalytics component:

  { domain, kpis: [{key,label,value,format}], charts: [{key,title,type,items}],
    insights: [{severity,message}] }
"""
from datetime import date, timedelta

from sqlalchemy import case, func as sqlfunc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.finance.models.accounts_payable import Invoice, InvoiceStatus, Vendor
from app.finance.models.accounts_receivable import CustomerInvoice, CustomerInvoiceStatus
from app.finance.models.expense import ExpenseReport
from app.finance.models.treasury import BankAccount

OPEN_AP = [InvoiceStatus.PENDING_APPROVAL, InvoiceStatus.APPROVED,
           InvoiceStatus.PARTIALLY_PAID, InvoiceStatus.OVERDUE]


async def finance_analytics(db: AsyncSession, tenant_id: str) -> dict:
    today = date.today()

    # AP aging buckets on open invoices (days past due).
    bucket = case(
        (Invoice.due_date >= today, "Current"),
        (Invoice.due_date >= today - timedelta(days=30), "1-30 days"),
        (Invoice.due_date >= today - timedelta(days=60), "31-60 days"),
        (Invoice.due_date >= today - timedelta(days=90), "61-90 days"),
        else_="90+ days",
    )
    aging_q = await db.execute(
        select(bucket, sqlfunc.coalesce(sqlfunc.sum(Invoice.balance_due), 0))
        .where(Invoice.tenant_id == tenant_id, Invoice.status.in_(OPEN_AP))
        .group_by(bucket)
    )
    aging_raw = dict(aging_q.all())
    aging_order = ["Current", "1-30 days", "31-60 days", "61-90 days", "90+ days"]
    aging = [{"label": b, "value": float(aging_raw.get(b, 0))} for b in aging_order]

    # Invoice status mix.
    status_q = await db.execute(
        select(Invoice.status, sqlfunc.count())
        .where(Invoice.tenant_id == tenant_id)
        .group_by(Invoice.status)
    )
    status_mix = [{"label": s.value if hasattr(s, "value") else str(s), "value": int(c)}
                  for s, c in status_q.all()]

    # Top vendors by YTD spend.
    vendor_q = await db.execute(
        select(Vendor.name, Vendor.total_spend_ytd)
        .where(Vendor.tenant_id == tenant_id)
        .order_by(Vendor.total_spend_ytd.desc())
        .limit(5)
    )
    top_vendors = [{"label": n, "value": float(s or 0)} for n, s in vendor_q.all()]

    # KPI scalars.
    ap_q = await db.execute(
        select(sqlfunc.coalesce(sqlfunc.sum(Invoice.balance_due), 0), sqlfunc.count())
        .where(Invoice.tenant_id == tenant_id, Invoice.status.in_(OPEN_AP))
    )
    total_ap, open_ap_count = ap_q.one()

    overdue_q = await db.execute(
        select(sqlfunc.count(), sqlfunc.coalesce(sqlfunc.sum(Invoice.balance_due), 0))
        .where(Invoice.tenant_id == tenant_id, Invoice.status.in_(OPEN_AP),
               Invoice.due_date < today)
    )
    overdue_count, overdue_amount = overdue_q.one()

    ar_q = await db.execute(
        select(sqlfunc.coalesce(sqlfunc.sum(CustomerInvoice.balance_due), 0))
        .where(CustomerInvoice.tenant_id == tenant_id,
               CustomerInvoice.status.in_([CustomerInvoiceStatus.SENT,
                                           CustomerInvoiceStatus.OVERDUE,
                                           CustomerInvoiceStatus.PARTIALLY_PAID]))
    )
    total_ar = float(ar_q.scalar() or 0)

    cash_q = await db.execute(
        select(sqlfunc.coalesce(sqlfunc.sum(BankAccount.current_balance), 0))
        .where(BankAccount.tenant_id == tenant_id, BankAccount.is_active == True)  # noqa: E712
    )
    total_cash = float(cash_q.scalar() or 0)

    # Expense compliance: average AI compliance score across reports.
    exp_q = await db.execute(
        select(sqlfunc.avg(ExpenseReport.ai_compliance_score), sqlfunc.count())
        .where(ExpenseReport.tenant_id == tenant_id)
    )
    avg_compliance, report_count = exp_q.one()

    dup_q = await db.execute(
        select(sqlfunc.count())
        .where(Invoice.tenant_id == tenant_id, Invoice.ai_duplicate_flag == True)  # noqa: E712
    )
    duplicate_flags = int(dup_q.scalar() or 0)

    insights = []
    if overdue_count:
        insights.append({
            "severity": "warning",
            "message": f"{int(overdue_count)} vendor invoices are past due "
                       f"(${float(overdue_amount or 0):,.0f} outstanding).",
        })
    if duplicate_flags:
        insights.append({
            "severity": "critical",
            "message": f"{duplicate_flags} invoices carry an AI duplicate flag — review before payment.",
        })
    if total_ap > total_cash > 0:
        insights.append({
            "severity": "warning",
            "message": "Open payables exceed current cash position — check the payment run schedule.",
        })
    if not insights:
        insights.append({"severity": "info", "message": "No finance anomalies detected in the current cycle."})

    return {
        "domain": "finance",
        "kpis": [
            {"key": "cash", "label": "Cash Position", "value": total_cash, "format": "currency"},
            {"key": "open_ap", "label": "Open Payables", "value": float(total_ap or 0), "format": "currency"},
            {"key": "open_ar", "label": "Open Receivables", "value": total_ar, "format": "currency"},
            {"key": "nwc", "label": "Net Working Capital", "value": total_cash + total_ar - float(total_ap or 0), "format": "currency"},
            {"key": "overdue", "label": "Overdue Invoices", "value": int(overdue_count or 0), "format": "number"},
            {"key": "compliance", "label": "Expense Compliance", "value": float(avg_compliance) if avg_compliance is not None else None, "format": "percent"},
        ],
        "charts": [
            {"key": "ap_aging", "title": "AP Aging (open balance $)", "type": "bar", "items": aging},
            {"key": "invoice_status", "title": "Invoice Status Mix", "type": "donut", "items": status_mix},
            {"key": "top_vendors", "title": "Top Vendors by YTD Spend", "type": "bar", "items": top_vendors},
        ],
        "insights": insights,
    }
