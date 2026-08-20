"""
KAEOS Finance Domain - Database Seed Script

Seeds the Finance tables with realistic double-entry bookkeeping, vendor,
customer, expense, treasury, tax, audit and reporting data.

The general ledger is REAL here: every ChartOfAccount balance is produced by
posting genuine opening-balance and monthly-activity journal entries through
app.finance.services.gl.post_journal_entry (the fail-closed keystone), and one
AP invoice is settled through app.finance.services.payments.record_vendor_payment
(the governed payment path). Nothing hardcodes current_balance, so the trial
balance derives the exact same figures it cross-checks against the cache and
balance_cache_drift is empty by construction on a fresh tenant.
"""
import asyncio
import logging
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select

from app.core.database import async_engine, AsyncSessionLocal
from app.core.domain_seed import SEED_TENANT as TENANT, already_seeded, new_id, run_standalone

# Models imports
from app.finance.models.core import (
    AccountType, ChartOfAccount, FiscalPeriod, FiscalPeriodStatus, FXRate,
)
from app.finance.models.accounts_payable import Vendor, Invoice, InvoiceStatus, VendorStatus
from app.finance.models.accounts_receivable import (
    Customer, CustomerInvoice, CustomerInvoiceStatus, CustomerStatus, Receipt,
)
from app.finance.models.budgeting import Budget, BudgetLine, Forecast, BudgetStatus
from app.finance.models.expense import (
    ExpenseReport, ExpenseItem, ExpensePolicy, ExpenseReportStatus, ExpenseCategory,
)
from app.finance.models.treasury import (
    BankAccount, CashFlow, Transfer, TransferStatus,
    AccountClassification as BankAccountClassification, CashFlowType,
)
from app.finance.models.tax import TaxFiling, FilingStatus, TaxRule, WithholdingConfig
from app.finance.models.reporting import (
    FinancialReport, ReportSchedule, ReportType, ReportStatus,
)
from app.finance.models.audit import (
    AuditFinding, AuditTrail, ControlTest, ControlTestResult,
    FindingSeverity, FindingStatus,
)
from app.finance.models.compliance import FinanceComplianceRule, SOXControl, SOXControlStatus
# Ops procurement models: the demo three-way-match chain (PO + lines + receipt)
# is built here so the FK chain resolves in one transaction and the matcher
# computes a GENUINE MATCHED and a GENUINE EXCEPTION.
from app.operations.models.procurement import (
    PurchaseOrder, POLineItem, GoodsReceipt, ProcurementStatus,
)
from app.finance.services.three_way_match import evaluate_three_way_match
from app.finance.services.gl import post_journal_entry
from app.finance.services.payments import accrue_invoice, record_vendor_payment

logger = logging.getLogger(__name__)


CONTROLLER = "maria.chen@acme.com"      # approves invoices, closes periods
TREASURY_OPS = "treasury.ops@acme.com"  # records payments (four-eyes vs approver)

def _month_start(anchor: date, back: int) -> date:
    """First day of the month ``back`` months before ``anchor``'s month."""
    y, m = anchor.year, anchor.month - back
    while m <= 0:
        m += 12
        y -= 1
    return date(y, m, 1)


async def seed_tenant(db, tenant: str) -> bool:
    """Seed the full finance domain for ``tenant`` in the given session.

    Idempotent: if the tenant already has a chart of accounts, nothing is
    touched and False is returned. Returns True when a fresh seed ran.
    """
    # A re-run must never duplicate ledger history.
    if await already_seeded(db, "Finance", ChartOfAccount, tenant):
        return False

    today = date.today()
    now = datetime.now(timezone.utc)
    # Seven full calendar months of activity, oldest first, ending last month.
    months = [_month_start(today, k) for k in range(7, 0, -1)]

    # 2. Chart of Accounts (Core GL). No current_balance is hardcoded here:
    # post_journal_entry moves the cache as each entry posts, so the cached
    # balance and the ledger-derived balance agree by construction.
    acc_checking = ChartOfAccount(id=new_id(), tenant_id=tenant, account_code="1010", account_name="SVB Operating Checking", account_type=AccountType.ASSET, normal_balance="DEBIT", is_bank_account=True, currency="USD", is_active=True)
    acc_mmkt = ChartOfAccount(id=new_id(), tenant_id=tenant, account_code="1020", account_name="Chase Money Market", account_type=AccountType.ASSET, normal_balance="DEBIT", is_bank_account=True, currency="USD", is_active=True)
    acc_ar = ChartOfAccount(id=new_id(), tenant_id=tenant, account_code="1200", account_name="Accounts Receivable (AR)", account_type=AccountType.ASSET, normal_balance="DEBIT", currency="USD", is_active=True)
    acc_ap = ChartOfAccount(id=new_id(), tenant_id=tenant, account_code="2000", account_name="Accounts Payable (AP)", account_type=AccountType.LIABILITY, normal_balance="CREDIT", currency="USD", is_active=True)
    acc_equity = ChartOfAccount(id=new_id(), tenant_id=tenant, account_code="3000", account_name="Common Stock & Paid-in Capital", account_type=AccountType.EQUITY, normal_balance="CREDIT", currency="USD", is_active=True)
    acc_revenue = ChartOfAccount(id=new_id(), tenant_id=tenant, account_code="4000", account_name="SaaS Subscription Revenue", account_type=AccountType.REVENUE, normal_balance="CREDIT", currency="USD", is_active=True)
    acc_infra = ChartOfAccount(id=new_id(), tenant_id=tenant, account_code="6010", account_name="Infra & Hosting Expense", account_type=AccountType.EXPENSE, normal_balance="DEBIT", currency="USD", is_active=True)
    acc_ga = ChartOfAccount(id=new_id(), tenant_id=tenant, account_code="6020", account_name="Office Supplies & G&A", account_type=AccountType.EXPENSE, normal_balance="DEBIT", currency="USD", is_active=True)
    acc_salaries = ChartOfAccount(id=new_id(), tenant_id=tenant, account_code="6100", account_name="Salaries & Wages", account_type=AccountType.EXPENSE, normal_balance="DEBIT", currency="USD", is_active=True)
    gl_accounts = [acc_checking, acc_mmkt, acc_ar, acc_ap, acc_equity,
                   acc_revenue, acc_infra, acc_ga, acc_salaries]
    for acc in gl_accounts:
        db.add(acc)
    await db.flush()

    # 1. Bank Accounts (Treasury), mapped to their GL cash accounts. The GL
    # postings below land these exact balances, so treasury and the ledger
    # report the same cash position.
    bank_svb = BankAccount(
        id=new_id(), tenant_id=tenant, account_name="Silicon Valley Checking",
        bank_name="SVB", account_number_masked="******4482",
        classification=BankAccountClassification.OPERATING, current_balance=1450000.00,
        available_balance=1420000.00, currency="USD", is_active=True, is_primary=True,
        gl_account_id=acc_checking.id,
        last_reconciled_date=today - timedelta(days=2)
    )
    bank_chase = BankAccount(
        id=new_id(), tenant_id=tenant, account_name="Chase Reserve Money Market",
        bank_name="JP Morgan Chase", account_number_masked="******8912",
        classification=BankAccountClassification.INVESTMENT, current_balance=2500000.00,
        available_balance=2500000.00, currency="USD", is_active=True,
        gl_account_id=acc_mmkt.id,
        last_reconciled_date=today - timedelta(days=7)
    )
    db.add_all([bank_svb, bank_chase])
    await db.flush()

    # FX rates so a EUR/GBP/INR-denominated account could post immediately.
    fx_rates = [
        FXRate(id=new_id(), tenant_id=tenant, currency="EUR", base_currency="USD", rate=Decimal("1.08000000"), as_of=today - timedelta(days=90)),
        FXRate(id=new_id(), tenant_id=tenant, currency="EUR", base_currency="USD", rate=Decimal("1.09200000"), as_of=today - timedelta(days=30)),
        FXRate(id=new_id(), tenant_id=tenant, currency="GBP", base_currency="USD", rate=Decimal("1.27100000"), as_of=today - timedelta(days=30)),
        FXRate(id=new_id(), tenant_id=tenant, currency="INR", base_currency="USD", rate=Decimal("0.01200000"), as_of=today - timedelta(days=30)),
    ]
    db.add_all(fx_rates)

    # 3. Vendors & AP Invoices
    vendors = [
        Vendor(id=new_id(), tenant_id=tenant, vendor_code="VND001", name="Amazon Web Services", legal_name="Amazon Web Services Inc.", email="billing@aws.amazon.com", phone="+1-800-201-1234", status=VendorStatus.ACTIVE, payment_terms_days=30, currency="USD", w9_on_file=True, risk_level="LOW", total_spend_ytd=420000.00, total_invoices_ytd=12, performance_score=98.0, address_line1="410 Terry Ave N", city="Seattle", state="WA", country="USA"),
        Vendor(id=new_id(), tenant_id=tenant, vendor_code="VND002", name="GCP Billing", legal_name="Google Cloud Platform", email="gc-billing@google.com", phone="+1-800-555-0199", status=VendorStatus.ACTIVE, payment_terms_days=15, currency="USD", w9_on_file=True, risk_level="LOW", total_spend_ytd=180000.00, total_invoices_ytd=6, performance_score=96.0, address_line1="1600 Amphitheatre Pkwy", city="Mountain View", state="CA", country="USA"),
        Vendor(id=new_id(), tenant_id=tenant, vendor_code="VND003", name="Acme Rent & Facilities", legal_name="Acme Commercial Realty LLC", email="lease@acme-rent.com", phone="+1-800-444-1234", status=VendorStatus.ACTIVE, payment_terms_days=30, currency="USD", w9_on_file=False, risk_level="MEDIUM", total_spend_ytd=120000.00, total_invoices_ytd=12, performance_score=85.0, address_line1="100 Broadway", city="New York", state="NY", country="USA"),
    ]
    for v in vendors:
        db.add(v)
    await db.flush()

    # -- Genuine three-way match demo chain -----------------------------------
    # PO-2026-081 (AWS): 10 units @ $3,545.00 = $35,450.00, fully received,
    # invoice bills exactly the PO -> matcher computes MATCHED.
    po_aws = PurchaseOrder(id=new_id(), tenant_id=tenant, po_number="PO-2026-081",
                           vendor_name="Amazon Web Services", vendor_id=vendors[0].id,
                           total_amount=35450.00, status=ProcurementStatus.RECEIVED)
    # PO-2026-082 (GCP): 6 units @ $2,500.00 = $15,000.00, fully received,
    # but the invoice bills $2,553.33/unit (overcharge past 2% tolerance)
    # -> matcher computes EXCEPTION.
    po_gcp = PurchaseOrder(id=new_id(), tenant_id=tenant, po_number="PO-2026-082",
                           vendor_name="GCP Billing", vendor_id=vendors[1].id,
                           total_amount=15000.00, status=ProcurementStatus.RECEIVED)
    db.add_all([po_aws, po_gcp])
    await db.flush()

    line_aws = POLineItem(id=new_id(), tenant_id=tenant, purchase_order_id=po_aws.id,
                          line_number=1, description="EC2 reserved compute",
                          quantity=10, unit_price=3545.00, amount=35450.00)
    line_gcp = POLineItem(id=new_id(), tenant_id=tenant, purchase_order_id=po_gcp.id,
                          line_number=1, description="GCP committed use",
                          quantity=6, unit_price=2500.00, amount=15000.00)
    db.add_all([line_aws, line_gcp])
    await db.flush()

    db.add_all([
        GoodsReceipt(id=new_id(), tenant_id=tenant, purchase_order_id=po_aws.id,
                     po_line_item_id=line_aws.id, receiver_name="Dwight Schrute",
                     received_quantity=10, status="SUCCESS"),
        GoodsReceipt(id=new_id(), tenant_id=tenant, purchase_order_id=po_gcp.id,
                     po_line_item_id=line_gcp.id, receiver_name="Dwight Schrute",
                     received_quantity=6, status="SUCCESS"),
    ])
    await db.flush()

    invoices = [
        # APPROVED with a recorded approver: eligible for the governed payment
        # path (record_vendor_payment) below.
        Invoice(id=new_id(), tenant_id=tenant, invoice_number="INV-AWS-2026-05", vendor_id=vendors[0].id, purchase_order_id=po_aws.id, gl_account_id=acc_infra.id, status=InvoiceStatus.APPROVED, approved_by=CONTROLLER, approved_at=now - timedelta(days=8), subtotal=35450.00, total_amount=35450.00, tax_amount=0.00, balance_due=35450.00, invoice_date=today - timedelta(days=10), due_date=today + timedelta(days=20), currency="USD", po_number="PO-2026-081", line_items=[{"description": "EC2 reserved compute", "qty": 10, "unit_price": 3545.00, "amount": 35450.00, "po_line_item_id": line_aws.id}], ai_duplicate_flag=False),
        Invoice(id=new_id(), tenant_id=tenant, invoice_number="INV-GCP-2026-05", vendor_id=vendors[1].id, purchase_order_id=po_gcp.id, gl_account_id=acc_infra.id, status=InvoiceStatus.PENDING_APPROVAL, subtotal=15320.00, total_amount=15320.00, tax_amount=0.00, balance_due=15320.00, invoice_date=today - timedelta(days=5), due_date=today + timedelta(days=10), currency="USD", po_number="PO-2026-082", line_items=[{"description": "GCP committed use", "qty": 6, "unit_price": 2553.33, "amount": 15320.00, "po_line_item_id": line_gcp.id}], ai_duplicate_flag=False),
        Invoice(id=new_id(), tenant_id=tenant, invoice_number="INV-RENT-2026-05", vendor_id=vendors[2].id, gl_account_id=acc_ga.id, status=InvoiceStatus.OVERDUE, approved_by=CONTROLLER, approved_at=now - timedelta(days=30), subtotal=10000.00, total_amount=10000.00, tax_amount=0.00, balance_due=10000.00, invoice_date=today - timedelta(days=35), due_date=today - timedelta(days=5), currency="USD", po_number=None, ai_duplicate_flag=False),
    ]
    for inv in invoices:
        db.add(inv)
    await db.flush()

    # Badge reflects REAL reconciliation, not a hardcoded string.
    for inv in invoices:
        res = await evaluate_three_way_match(db, tenant, inv)
        inv.three_way_match_status = res["status"]
        inv.po_matched = bool(res.get("po_matched"))
        inv.receipt_matched = bool(res.get("receipt_matched"))
    await db.flush()

    # 4. Customers & AR Invoices
    customers = [
        Customer(id=new_id(), tenant_id=tenant, customer_code="CST001", name="Stark Industries", legal_name="Stark Industries Global", email="finance@stark.com", phone="+1-212-555-3000", status=CustomerStatus.ACTIVE, credit_limit=500000.00, payment_terms_days=30, currency="USD", total_revenue_ytd=1250000.00, total_outstanding=150000.00, days_sales_outstanding=28, ai_churn_risk=0.05, aging_current=100000.00, aging_30=50000.00, aging_60=0.00, aging_90=0.00, aging_over_90=0.00),
        Customer(id=new_id(), tenant_id=tenant, customer_code="CST002", name="Wayne Enterprises", legal_name="Wayne Enterprises Inc", email="ap@wayne.corp", phone="+1-312-555-8888", status=CustomerStatus.ACTIVE, credit_limit=1000000.00, payment_terms_days=45, currency="USD", total_revenue_ytd=680000.00, total_outstanding=200000.00, days_sales_outstanding=42, ai_churn_risk=0.15, aging_current=150000.00, aging_30=0.00, aging_60=50000.00, aging_90=0.00, aging_over_90=0.00),
    ]
    for c in customers:
        db.add(c)
    await db.flush()

    customer_invoices = [
        CustomerInvoice(id=new_id(), tenant_id=tenant, invoice_number="INV-CST-1001", customer_id=customers[0].id, status=CustomerInvoiceStatus.SENT, subtotal=100000.00, total_amount=100000.00, tax_amount=0.00, balance_due=100000.00, invoice_date=today - timedelta(days=12), due_date=today + timedelta(days=18), currency="USD", dunning_level=0),
        CustomerInvoice(id=new_id(), tenant_id=tenant, invoice_number="INV-CST-1002", customer_id=customers[1].id, status=CustomerInvoiceStatus.OVERDUE, subtotal=50000.00, total_amount=50000.00, tax_amount=0.00, balance_due=50000.00, invoice_date=today - timedelta(days=62), due_date=today - timedelta(days=17), currency="USD", dunning_level=2),
        # Fully collected: gives the Receipt below a genuine invoice to settle.
        CustomerInvoice(id=new_id(), tenant_id=tenant, invoice_number="INV-CST-0998", customer_id=customers[0].id, status=CustomerInvoiceStatus.PAID, subtotal=120000.00, total_amount=120000.00, tax_amount=0.00, balance_due=0.00, invoice_date=today - timedelta(days=70), due_date=today - timedelta(days=40), currency="USD", dunning_level=0),
    ]
    for cinv in customer_invoices:
        db.add(cinv)
    await db.flush()

    # 5. Budgets & Forecasts
    budget = Budget(
        id=new_id(), tenant_id=tenant, name="FY2026 R&D Budget", budget_type="OPEX",
        fiscal_year=2026, status=BudgetStatus.ACTIVE, total_planned=1200000.00,
        total_actual=485000.00, total_variance=715000.00, variance_pct=5.4,
        department="Engineering", owner_id="finance_agent"
    )
    db.add(budget)
    await db.flush()

    budget_lines = [
        BudgetLine(id=new_id(), tenant_id=tenant, budget_id=budget.id, account_id=acc_infra.id, category="Hosting", period=1, period_label="Jan 2026", planned_amount=50000.00, actual_amount=52000.00, committed_amount=0.00, variance=-2000.00),
        BudgetLine(id=new_id(), tenant_id=tenant, budget_id=budget.id, account_id=acc_infra.id, category="Hosting", period=2, period_label="Feb 2026", planned_amount=50000.00, actual_amount=48000.00, committed_amount=0.00, variance=2000.00),
        BudgetLine(id=new_id(), tenant_id=tenant, budget_id=budget.id, account_id=acc_salaries.id, category="Salaries", period=1, period_label="Jan 2026", planned_amount=100000.00, actual_amount=98000.00, committed_amount=0.00, variance=2000.00),
    ]
    for bl in budget_lines:
        db.add(bl)

    forecast = Forecast(
        id=new_id(), tenant_id=tenant, forecast_name="Q3 Cash Flow Projection", forecast_type="ROLLING",
        scenario="BASE", period_start=date(2026, 7, 1), period_end=date(2026, 9, 30),
        total_forecast=450000.00, confidence_score=0.92
    )
    db.add(forecast)
    await db.flush()

    # 6. Expense Reports
    # employee_id is an FK to hr_employees.id (a UUID) - use a real row. When
    # the HR domain has not seeded this tenant yet (isolated finance seed, unit
    # tests), create one minimal employee so the NOT NULL FK holds.
    from app.hr.models.core import HREmployee
    _emp = (await db.execute(
        select(HREmployee.id).where(HREmployee.tenant_id == tenant).limit(1)
    )).scalar_one_or_none()
    if _emp is None:
        emp_row = HREmployee(
            id=new_id(), tenant_id=tenant, first_name="Jordan", last_name="Rivera",
            email="jordan.rivera@acme.com", hire_date=date(2024, 3, 4),
            job_title="Enterprise Account Executive",
        )
        db.add(emp_row)
        await db.flush()
        _emp = emp_row.id
    exp_report = ExpenseReport(
        id=new_id(), tenant_id=tenant, report_number="EXP-2026-004", title="Q1 Technical Sales Travel",
        employee_id=_emp, status=ExpenseReportStatus.PENDING_APPROVAL, total_amount=1240.00,
        approved_amount=0.00, currency="USD", ai_compliance_score=94.5,
        ai_policy_violations=[]
    )
    db.add(exp_report)
    await db.flush()

    expense_items = [
        ExpenseItem(id=new_id(), tenant_id=tenant, report_id=exp_report.id, line_number=1, expense_date=today - timedelta(days=4), category=ExpenseCategory.TRAVEL, description="Flight SF to NYC", merchant="United Airlines", amount=850.00, receipt_path="/receipts/united-850.pdf", is_within_policy=True, is_billable=False),
        ExpenseItem(id=new_id(), tenant_id=tenant, report_id=exp_report.id, line_number=2, expense_date=today - timedelta(days=3), category=ExpenseCategory.MEALS, description="Client dinner Stark Ind", merchant="Del Posto", amount=390.00, receipt_path="/receipts/delposto-390.pdf", is_within_policy=True, is_billable=True),
    ]
    for item in expense_items:
        db.add(item)
    await db.flush()

    # Expense policies: the rules the AI expense agent enforces. The seeded
    # items above sit within these limits, so the compliance story is coherent.
    expense_policies = [
        ExpensePolicy(id=new_id(), tenant_id=tenant, name="Corporate Travel Policy", category=ExpenseCategory.TRAVEL, description="Air travel booked 14+ days out in economy; itemized receipt required for every leg.", max_amount_per_item=2500.00, max_amount_per_report=7500.00, receipt_required_above=25.00, auto_approve_below=100.00, manager_approval_below=5000.00, is_active=True, effective_date=date(2026, 1, 1)),
        ExpensePolicy(id=new_id(), tenant_id=tenant, name="Meals & Entertainment Policy", category=ExpenseCategory.MEALS, description="Client meals up to $400 per sitting with attendee list; alcohol capped at 30% of the check.", max_amount_per_item=400.00, max_daily_total=500.00, receipt_required_above=25.00, auto_approve_below=100.00, manager_approval_below=2000.00, is_active=True, effective_date=date(2026, 1, 1)),
    ]
    db.add_all(expense_policies)

    # 7. Cash Flow (Treasury) - recent actuals plus two forecast rows, all tied
    # to the operating account.
    cash_flows = [
        CashFlow(id=new_id(), tenant_id=tenant, bank_account_id=bank_svb.id, flow_date=today - timedelta(days=1), flow_type=CashFlowType.OPERATING_INFLOW, category="Customer Subscription", description="Stark Industries monthly subscription", amount=12000.00, currency="USD", is_forecast=False, source_module="AR", fiscal_year=today.year),
        CashFlow(id=new_id(), tenant_id=tenant, bank_account_id=bank_svb.id, flow_date=today - timedelta(days=2), flow_type=CashFlowType.OPERATING_OUTFLOW, category="Hosting Bills", description="AWS reserved compute settlement", amount=-8200.00, currency="USD", is_forecast=False, source_module="AP", fiscal_year=today.year),
        CashFlow(id=new_id(), tenant_id=tenant, bank_account_id=bank_svb.id, flow_date=today - timedelta(days=5), flow_type=CashFlowType.OPERATING_INFLOW, category="Customer Subscription", description="Wayne Enterprises annual true-up", amount=46000.00, currency="USD", is_forecast=False, source_module="AR", fiscal_year=today.year),
        CashFlow(id=new_id(), tenant_id=tenant, bank_account_id=bank_svb.id, flow_date=today - timedelta(days=6), flow_type=CashFlowType.OPERATING_OUTFLOW, category="Payroll Run", description="Semi-monthly payroll disbursement", amount=-70000.00, currency="USD", is_forecast=False, source_module="PAYROLL", fiscal_year=today.year),
        CashFlow(id=new_id(), tenant_id=tenant, bank_account_id=bank_svb.id, flow_date=today - timedelta(days=9), flow_type=CashFlowType.OPERATING_OUTFLOW, category="Insurance Premium", description="D&O policy quarterly premium", amount=-5400.00, currency="USD", is_forecast=False, source_module="AP", fiscal_year=today.year),
        CashFlow(id=new_id(), tenant_id=tenant, bank_account_id=bank_svb.id, flow_date=today - timedelta(days=12), flow_type=CashFlowType.OPERATING_INFLOW, category="Customer Subscription", description="Mid-market cohort renewals", amount=28500.00, currency="USD", is_forecast=False, source_module="AR", fiscal_year=today.year),
        CashFlow(id=new_id(), tenant_id=tenant, bank_account_id=bank_svb.id, flow_date=today - timedelta(days=15), flow_type=CashFlowType.OPERATING_OUTFLOW, category="Tax Payment", description="CA sales tax remittance Q2", amount=-18500.00, currency="USD", is_forecast=False, source_module="TAX", fiscal_year=today.year),
        CashFlow(id=new_id(), tenant_id=tenant, bank_account_id=bank_chase.id, flow_date=today - timedelta(days=18), flow_type=CashFlowType.INVESTING_INFLOW, category="Interest Income", description="Money market monthly interest", amount=9100.00, currency="USD", is_forecast=False, source_module="TREASURY", fiscal_year=today.year),
        CashFlow(id=new_id(), tenant_id=tenant, bank_account_id=bank_svb.id, flow_date=today + timedelta(days=7), flow_type=CashFlowType.OPERATING_INFLOW, category="Customer Subscription", description="Projected enterprise renewals", amount=95000.00, currency="USD", is_forecast=True, forecast_confidence=0.86, source_module="AR", fiscal_year=today.year),
        CashFlow(id=new_id(), tenant_id=tenant, bank_account_id=bank_svb.id, flow_date=today + timedelta(days=12), flow_type=CashFlowType.OPERATING_OUTFLOW, category="Payroll Run", description="Projected semi-monthly payroll", amount=-71000.00, currency="USD", is_forecast=True, forecast_confidence=0.97, source_module="PAYROLL", fiscal_year=today.year),
    ]
    db.add_all(cash_flows)

    # 8. Tax Filings + the rules behind them (same jurisdictions, so the Tax
    # tab reads as one coherent story).
    tax_filings = [
        TaxFiling(id=new_id(), tenant_id=tenant, filing_type="FEDERAL_INCOME", jurisdiction="US Federal - IRS", period="FY2025", fiscal_year=2025, status=FilingStatus.IN_PROGRESS, tax_liability=245000.00, tax_paid=0.00, due_date=date(2026, 7, 15), form_number="Form 1120"),
        TaxFiling(id=new_id(), tenant_id=tenant, filing_type="STATE_SALES", jurisdiction="State of California - CDTFA", period="Q1 2026", fiscal_year=2026, status=FilingStatus.FILED, tax_liability=18500.00, tax_paid=18500.00, due_date=date(2026, 4, 30), form_number="CDTFA-401"),
    ]
    db.add_all(tax_filings)

    tax_rules = [
        TaxRule(id=new_id(), tenant_id=tenant, name="US Federal Corporate Income Tax", tax_type="INCOME", jurisdiction="US Federal - IRS", rate=0.21, effective_date=date(2018, 1, 1), is_progressive=False, description="Flat corporate rate under the Tax Cuts and Jobs Act; drives the Form 1120 liability estimate.", is_active=True),
        TaxRule(id=new_id(), tenant_id=tenant, name="California Sales & Use Tax", tax_type="SALES", jurisdiction="State of California - CDTFA", rate=0.0725, effective_date=date(2017, 7, 1), is_progressive=False, exemptions=["Groceries", "Prescription medicine"], description="Statewide base rate applied to taxable CA sales; district add-ons tracked per invoice.", is_active=True),
        TaxRule(id=new_id(), tenant_id=tenant, name="California Corporate Franchise Tax", tax_type="INCOME", jurisdiction="State of California - FTB", rate=0.0884, effective_date=date(2020, 1, 1), is_progressive=False, description="Applies to net income apportioned to California; minimum franchise tax $800.", is_active=True),
    ]
    db.add_all(tax_rules)

    # Employee withholding configuration, tied to the same employee as the
    # expense report so the HR link is real.
    db.add(WithholdingConfig(
        id=new_id(), tenant_id=tenant, employee_id=_emp, filing_status="SINGLE",
        federal_allowances=2, state="CA", state_allowances=1,
        additional_withholding=150.00, w4_year=2026,
        exempt_from_withholding=False, effective_date=date(2026, 1, 1),
    ))

    # 9. Reports (Reporting) + schedules that keep them coming.
    reports = [
        FinancialReport(
            id=new_id(), tenant_id=tenant, report_type=ReportType.INCOME_STATEMENT,
            title="Q1 2026 Profit & Loss", status=ReportStatus.COMPLETED,
            period_start=date(2026, 1, 1), period_end=date(2026, 3, 31),
            generated_at=datetime.utcnow(),
            report_data={"net_income": 350000.00, "total_revenue": 1850000.00, "total_expenses": 1500000.00},
            summary={"net_income": 350000.00, "total_revenue": 1850000.00, "total_expenses": 1500000.00},
            ai_anomalies=[]
        ),
    ]
    db.add_all(reports)

    report_schedules = [
        ReportSchedule(id=new_id(), tenant_id=tenant, name="Monthly P&L to Leadership", report_type=ReportType.INCOME_STATEMENT, frequency="MONTHLY", recipients=["cfo@acme.com", CONTROLLER], format="PDF", is_active=True, last_run_at=now - timedelta(days=14), next_run_at=now + timedelta(days=16), created_by=CONTROLLER),
        ReportSchedule(id=new_id(), tenant_id=tenant, name="Weekly Cash Position", report_type=ReportType.CASH_FLOW_STATEMENT, frequency="WEEKLY", recipients=[TREASURY_OPS], format="EXCEL", is_active=True, last_run_at=now - timedelta(days=6), next_run_at=now + timedelta(days=1), created_by=TREASURY_OPS),
    ]
    db.add_all(report_schedules)

    # 10. Audit Findings & SOX Controls
    controls = [
        SOXControl(id=new_id(), tenant_id=tenant, control_id_code="SOX-AC-01", name="Journal Entry Approval Controls", description="Ensure all JEs over $10k have manager sign-off.", control_type="PREVENTATIVE", frequency="TRANSACTIONAL", nature="MANUAL", area="General Ledger", status=SOXControlStatus.EFFECTIVE, risk_level="HIGH", ai_effectiveness_score=98.5),
        SOXControl(id=new_id(), tenant_id=tenant, control_id_code="SOX-AP-03", name="Vendor Master Setup Controls", description="Verify W-9 is present for new vendors before invoice creation.", control_type="PREVENTATIVE", frequency="DAILY", nature="SYSTEM", area="Accounts Payable", status=SOXControlStatus.NEEDS_IMPROVEMENT, risk_level="MEDIUM", ai_effectiveness_score=68.0),
    ]
    for ctrl in controls:
        db.add(ctrl)
    await db.flush()

    # Control tests: the evidence behind each control's status. The W-9 test's
    # exceptions match the open audit finding below.
    control_tests = [
        ControlTest(id=new_id(), tenant_id=tenant, control_id=controls[0].id, test_date=today - timedelta(days=21), tester="internal.audit@acme.com", test_procedure="Sampled 25 journal entries over $10k and verified manager sign-off in the approval log.", sample_size=25, exceptions_found=0, result=ControlTestResult.EFFECTIVE, conclusion="All sampled entries carried documented approval before posting. Control operating effectively.", ai_assisted=True, ai_test_summary="Automated sample selection and approval-log matching found zero unapproved postings."),
        ControlTest(id=new_id(), tenant_id=tenant, control_id=controls[1].id, test_date=today - timedelta(days=14), tester="internal.audit@acme.com", test_procedure="Traced 12 newly onboarded vendors to W-9 documentation on file.", sample_size=12, exceptions_found=3, result=ControlTestResult.PARTIALLY_EFFECTIVE, conclusion="3 of 12 vendors lacked a verified W-9 at invoice time. Remediation tracked under finding AUD-2026-001.", ai_assisted=True, ai_test_summary="Document matcher flagged 3 vendor files with missing or unverified W-9 attachments."),
    ]
    db.add_all(control_tests)

    findings = [
        AuditFinding(id=new_id(), tenant_id=tenant, finding_number="AUD-2026-001", title="Missing W-9 Documentation", severity=FindingSeverity.MEDIUM, status=FindingStatus.OPEN, area="Accounts Payable", control_id=controls[1].id, description="3 new vendors added without verified W-9 documents on file.", financial_impact=0.00, remediation_owner="AP Lead", remediation_plan="Reach out to vendors to collect W-9 documents and implement hard blocker in system.", ai_detected=True),
    ]
    for find in findings:
        db.add(find)

    # 11. Compliance Rules
    rules = [
        FinanceComplianceRule(id=new_id(), tenant_id=tenant, regulation="GAAP", section="ASC 606", name="Revenue Recognition Contract Assets", description="Revenue from SaaS contracts must be recognized straight-line over contract term.", severity="CRITICAL", is_blocking=True, applies_to="CustomerInvoice"),
        FinanceComplianceRule(id=new_id(), tenant_id=tenant, regulation="SOX", section="Section 404", name="Double Entry Balance Check", description="Debits must equal Credits for all approved Journal Entries.", severity="CRITICAL", is_blocking=True, applies_to="JournalEntry"),
    ]
    for ru in rules:
        db.add(ru)
    await db.flush()

    # ── 12. The general ledger itself ────────────────────────────────────────
    # Every balance below is POSTED through the GL keystone, which also moves
    # ChartOfAccount.current_balance in the same transaction. Final balances:
    #   1010 $1,450,000  1020 $2,500,000  1200 $350,000  2000 $30,000
    #   3000 $3,865,000  4000 $1,850,000  6010 $420,000  6020 $75,000  6100 $950,000
    async def _je(description, lines, entry_date, source, reference=None):
        return await post_journal_entry(
            db, tenant, lines=lines, description=description,
            entry_date=entry_date, reference=reference,
            source_module=source, created_by=CONTROLLER,
        )

    # Opening balances at the start of the activity window.
    je_opening = await _je(
        "Opening balances brought forward",
        [
            {"account_code": "1010", "debit": 1450000.00, "description": "Opening operating cash"},
            {"account_code": "1020", "debit": 2250000.00, "description": "Opening money market reserve"},
            {"account_code": "1200", "debit": 250000.00, "description": "Opening receivables"},
            {"account_code": "2000", "credit": 85000.00, "description": "Opening payables"},
            {"account_code": "3000", "credit": 3865000.00, "description": "Paid-in capital"},
        ],
        months[0], "OPENING", reference="FY-OPEN",
    )

    monthly_revenue = [240000, 245000, 250000, 260000, 270000, 280000, 305000]      # 1,850,000
    monthly_collections = [230000, 240000, 245000, 255000, 260000, 270000, 250000]  # 1,750,000
    monthly_payroll = [130000, 132000, 134000, 136000, 138000, 140000, 140000]      #   950,000
    monthly_infra = [52000, 53500, 54000, 55000, 56050, 56500, 57500]               #   384,550
    ga_by_month = {1: 20000, 3: 22000, 5: 23000}                                    #    65,000
    settle_by_month = {3: 110000, 4: 111000, 5: 112000, 6: 116550}                  #   449,550

    je_collections = []
    for i, m in enumerate(months):
        label = m.strftime("%B %Y")
        await _je(f"SaaS subscription revenue recognized, {label}",
                  [{"account_code": "1200", "debit": monthly_revenue[i]},
                   {"account_code": "4000", "credit": monthly_revenue[i]}],
                  m.replace(day=25), "AR", reference=f"REV-{m.strftime('%Y%m')}")
        je_collections.append(await _je(
            f"Customer receipts applied to receivables, {label}",
            [{"account_code": "1010", "debit": monthly_collections[i]},
             {"account_code": "1200", "credit": monthly_collections[i]}],
            m.replace(day=28), "AR", reference=f"RCPT-{m.strftime('%Y%m')}"))
        await _je(f"Payroll run, {label}",
                  [{"account_code": "6100", "debit": monthly_payroll[i]},
                   {"account_code": "1010", "credit": monthly_payroll[i]}],
                  m.replace(day=26), "PAYROLL", reference=f"PR-{m.strftime('%Y%m')}")
        await _je(f"Cloud infrastructure accrual, {label}",
                  [{"account_code": "6010", "debit": monthly_infra[i]},
                   {"account_code": "2000", "credit": monthly_infra[i]}],
                  m.replace(day=15), "AP", reference=f"INFRA-{m.strftime('%Y%m')}")
        if i in ga_by_month:
            await _je(f"Office supplies and G&A spend, {label}",
                      [{"account_code": "6020", "debit": ga_by_month[i]},
                       {"account_code": "1010", "credit": ga_by_month[i]}],
                      m.replace(day=10), "AP", reference=f"GA-{m.strftime('%Y%m')}")
        if i in settle_by_month:
            await _je(f"Vendor payment run settling accrued payables, {label}",
                      [{"account_code": "2000", "debit": settle_by_month[i]},
                       {"account_code": "1010", "credit": settle_by_month[i]}],
                      m.replace(day=20), "AP", reference=f"PAYRUN-{m.strftime('%Y%m')}")

    # Treasury sweep: excess operating cash into the money market reserve. The
    # Transfer row links to the same journal entry that moved the GL.
    je_transfer = await _je(
        "Treasury sweep of excess operating cash into money market reserve",
        [{"account_code": "1020", "debit": 250000.00},
         {"account_code": "1010", "credit": 250000.00}],
        months[-1].replace(day=5), "TREASURY", reference="XFER-2026-018",
    )
    db.add(Transfer(
        id=new_id(), tenant_id=tenant,
        from_account_id=bank_svb.id, to_account_id=bank_chase.id,
        amount=250000.00, currency="USD", status=TransferStatus.COMPLETED,
        transfer_date=months[-1].replace(day=5),
        description="Quarterly sweep of excess operating cash into money market reserve",
        reference="XFER-2026-018", requested_by=TREASURY_OPS,
        approved_by=CONTROLLER, approved_at=now,
        journal_entry_id=je_transfer.id,
    ))

    # Accrue the approved-but-unpaid rent invoice so the P&L and AP balance
    # reflect the liability (accrual basis, same path the app uses).
    await accrue_invoice(db, tenant, invoices[2], actor=CONTROLLER)

    # Customer receipt against the PAID AR invoice, tied to the most recent
    # collections journal entry.
    db.add(Receipt(
        id=new_id(), tenant_id=tenant, customer_id=customers[0].id,
        invoice_id=customer_invoices[2].id, receipt_number="RCT-2026-000317",
        receipt_date=months[-1].replace(day=28), amount=120000.00, currency="USD",
        method="WIRE", reference_number="FEDWIRE-8802341",
        bank_account_id=bank_svb.id, journal_entry_id=je_collections[-1].id,
        is_reconciled=True, reconciled_at=now,
    ))
    await db.flush()

    # ── 13. Governed vendor payment ──────────────────────────────────────────
    # The AWS invoice flows through record_vendor_payment: accrual + settlement
    # entries post through the GL keystone, the Payment row links its journal
    # entry, and the four-eyes control is exercised (approver != payer).
    payment = await record_vendor_payment(
        db, tenant,
        invoice_id=invoices[0].id, amount=35450.00, method="ACH",
        reference_number="ACH-20260806-0148", bank_account_id=None,
        recorded_by=TREASURY_OPS,
    )

    # ── 14. Period locks + audit trail over what actually happened ───────────
    for m in months[:3]:
        db.add(FiscalPeriod(
            id=new_id(), tenant_id=tenant, fiscal_year=m.year, fiscal_period=m.month,
            status=FiscalPeriodStatus.CLOSED, closed_by=CONTROLLER,
            closed_at=now - timedelta(days=(today - m).days - 20),
            note="Monthly close completed",
        ))

    audit_trail = [
        AuditTrail(id=new_id(), tenant_id=tenant, event_type="POST", entity_type="JournalEntry", entity_id=je_opening.id, entity_description=f"Opening balances posted as {je_opening.entry_number}", performed_by="SYSTEM", performed_by_type="SYSTEM", timestamp=now - timedelta(days=45)),
        AuditTrail(id=new_id(), tenant_id=tenant, event_type="APPROVE", entity_type="Invoice", entity_id=invoices[0].id, entity_description="INV-AWS-2026-05 approved for payment after three-way match", field_changed="status", old_value="PENDING_APPROVAL", new_value="APPROVED", performed_by=CONTROLLER, performed_by_type="USER", timestamp=now - timedelta(days=8)),
        AuditTrail(id=new_id(), tenant_id=tenant, event_type="POST", entity_type="Payment", entity_id=payment.id, entity_description=f"Vendor payment {payment.payment_number} recorded against INV-AWS-2026-05", performed_by=TREASURY_OPS, performed_by_type="USER", timestamp=now - timedelta(hours=6)),
        AuditTrail(id=new_id(), tenant_id=tenant, event_type="UPDATE", entity_type="SOXControl", entity_id=controls[1].id, entity_description="Vendor Master Setup Controls downgraded after W-9 test exceptions", field_changed="status", old_value="EFFECTIVE", new_value="NEEDS_IMPROVEMENT", performed_by="AI_AGENT", performed_by_type="AI_AGENT", timestamp=now - timedelta(days=13)),
    ]
    db.add_all(audit_trail)

    await db.commit()
    logger.info(f"[SUCCESS] Seeded Finance database for {tenant}:")
    logger.info(f"   - {len(gl_accounts)} GL accounts, ledger-backed via posted journal entries")
    logger.info(f"   - {len(vendors)} vendors, {len(invoices)} bills, 1 governed payment ({payment.payment_number})")
    logger.info(f"   - {len(customers)} customers, {len(customer_invoices)} customer invoices, 1 receipt")
    logger.info(f"   - {len(tax_rules)} tax rules, {len(fx_rates)} FX rates, 3 closed fiscal periods")
    logger.info(f"   - {len(controls)} SOX controls, {len(control_tests)} control tests, {len(findings)} audit findings")
    logger.info(f"   - {len(rules)} compliance rules, {len(audit_trail)} audit trail events")
    return True


async def seed(tenant: str | None = None) -> bool:
    return await run_standalone(async_engine, AsyncSessionLocal, seed_tenant, tenant or TENANT)

if __name__ == "__main__":
    asyncio.run(seed())
