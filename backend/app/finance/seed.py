"""
KAEOS Finance Domain — Database Seed Script
Seeds the Finance tables with realistic double-entry bookkeeping, vendor, customer,
expense, treasury, and audit data.
"""
import asyncio
import uuid
from datetime import date, datetime, timedelta

from app.core.database import async_engine, AsyncSessionLocal
from app.models.domain import Base

# Models imports
from app.finance.models.core import ChartOfAccount
from app.finance.models.accounts_payable import Vendor, Invoice, InvoiceStatus, VendorStatus
from app.finance.models.accounts_receivable import Customer, CustomerInvoice, CustomerInvoiceStatus, CustomerStatus
from app.finance.models.budgeting import Budget, BudgetLine, Forecast, BudgetStatus
from app.finance.models.expense import ExpenseReport, ExpenseItem, ExpenseReportStatus, ExpenseCategory
from app.finance.models.treasury import BankAccount, CashFlow, AccountClassification as BankAccountClassification, CashFlowType
from app.finance.models.tax import TaxFiling, FilingStatus
from app.finance.models.reporting import FinancialReport, ReportType, ReportStatus
from app.finance.models.audit import AuditFinding, FindingSeverity, FindingStatus
from app.finance.models.compliance import FinanceComplianceRule, SOXControl, SOXControlStatus

TENANT = "tenant_acme"  # demo tenant — matches seed_demo_user and dev-mode tenant

def _id():
    return str(uuid.uuid4())

async def seed():
    # Ensure tables are built
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as db:
        # 1. Bank Accounts (Treasury)
        bank_accounts = [
            BankAccount(
                id=_id(), tenant_id=TENANT, account_name="Silicon Valley Checking",
                bank_name="SVB", account_number_masked="******4482",
                classification=BankAccountClassification.OPERATING, current_balance=1450000.00,
                available_balance=1420000.00, currency="USD", is_active=True,
                last_reconciled_date=date.today() - timedelta(days=2)
            ),
            BankAccount(
                id=_id(), tenant_id=TENANT, account_name="Chase Reserve Money Market",
                bank_name="JP Morgan Chase", account_number_masked="******8912",
                classification=BankAccountClassification.INVESTMENT, current_balance=2500000.00,
                available_balance=2500000.00, currency="USD", is_active=True,
                last_reconciled_date=date.today() - timedelta(days=7)
            )
        ]
        for ba in bank_accounts:
            db.add(ba)
        await db.flush()

        # 2. Chart of Accounts (Core GL)
        gl_accounts = [
            ChartOfAccount(id=_id(), tenant_id=TENANT, account_code="1010", account_name="SVB Operating Checking", account_type="ASSET", current_balance=1450000.00, currency="USD", is_active=True),
            ChartOfAccount(id=_id(), tenant_id=TENANT, account_code="1020", account_name="Chase Money Market", account_type="ASSET", current_balance=2500000.00, currency="USD", is_active=True),
            ChartOfAccount(id=_id(), tenant_id=TENANT, account_code="1200", account_name="Accounts Receivable (AR)", account_type="ASSET", current_balance=350000.00, currency="USD", is_active=True),
            ChartOfAccount(id=_id(), tenant_id=TENANT, account_code="2000", account_name="Accounts Payable (AP)", account_type="LIABILITY", current_balance=120000.00, currency="USD", is_active=True),
            ChartOfAccount(id=_id(), tenant_id=TENANT, account_code="4000", account_name="SaaS Subscription Revenue", account_type="REVENUE", current_balance=1850000.00, currency="USD", is_active=True),
            ChartOfAccount(id=_id(), tenant_id=TENANT, account_code="6010", account_name="Infra & Hosting Expense", account_type="EXPENSE", current_balance=420000.00, currency="USD", is_active=True),
            ChartOfAccount(id=_id(), tenant_id=TENANT, account_code="6020", account_name="Office Supplies & G&A", account_type="EXPENSE", current_balance=65000.00, currency="USD", is_active=True),
            ChartOfAccount(id=_id(), tenant_id=TENANT, account_code="6100", account_name="Salaries & Wages", account_type="EXPENSE", current_balance=950000.00, currency="USD", is_active=True),
        ]
        for acc in gl_accounts:
            db.add(acc)
        await db.flush()

        # 3. Vendors & AP Invoices
        vendors = [
            Vendor(id=_id(), tenant_id=TENANT, vendor_code="VND001", name="Amazon Web Services", legal_name="Amazon Web Services Inc.", email="billing@aws.amazon.com", phone="+1-800-201-1234", status=VendorStatus.ACTIVE, payment_terms_days=30, currency="USD", w9_on_file=True, risk_level="LOW", total_spend_ytd=420000.00, total_invoices_ytd=12, performance_score=98.0, address_line1="410 Terry Ave N", city="Seattle", state="WA", country="USA"),
            Vendor(id=_id(), tenant_id=TENANT, vendor_code="VND002", name="GCP Billing", legal_name="Google Cloud Platform", email="gc-billing@google.com", phone="+1-800-555-0199", status=VendorStatus.ACTIVE, payment_terms_days=15, currency="USD", w9_on_file=True, risk_level="LOW", total_spend_ytd=180000.00, total_invoices_ytd=6, performance_score=96.0, address_line1="1600 Amphitheatre Pkwy", city="Mountain View", state="CA", country="USA"),
            Vendor(id=_id(), tenant_id=TENANT, vendor_code="VND003", name="Acme Rent & Facilities", legal_name="Acme Commercial Realty LLC", email="lease@acme-rent.com", phone="+1-800-444-1234", status=VendorStatus.ACTIVE, payment_terms_days=30, currency="USD", w9_on_file=False, risk_level="MEDIUM", total_spend_ytd=120000.00, total_invoices_ytd=12, performance_score=85.0, address_line1="100 Broadway", city="New York", state="NY", country="USA"),
        ]
        for v in vendors:
            db.add(v)
        await db.flush()

        invoices = [
            Invoice(id=_id(), tenant_id=TENANT, invoice_number="INV-AWS-2026-05", vendor_id=vendors[0].id, status=InvoiceStatus.APPROVED, subtotal=35450.00, total_amount=35450.00, tax_amount=0.00, balance_due=35450.00, invoice_date=date.today() - timedelta(days=10), due_date=date.today() + timedelta(days=20), currency="USD", po_number="PO-2026-081", three_way_match_status="MATCHED", ai_duplicate_flag=False),
            Invoice(id=_id(), tenant_id=TENANT, invoice_number="INV-GCP-2026-05", vendor_id=vendors[1].id, status=InvoiceStatus.PENDING_APPROVAL, subtotal=15320.00, total_amount=15320.00, tax_amount=0.00, balance_due=15320.00, invoice_date=date.today() - timedelta(days=5), due_date=date.today() + timedelta(days=10), currency="USD", po_number="PO-2026-082", three_way_match_status="PENDING_RECEIPT", ai_duplicate_flag=False),
            Invoice(id=_id(), tenant_id=TENANT, invoice_number="INV-RENT-2026-05", vendor_id=vendors[2].id, status=InvoiceStatus.OVERDUE, subtotal=10000.00, total_amount=10000.00, tax_amount=0.00, balance_due=10000.00, invoice_date=date.today() - timedelta(days=35), due_date=date.today() - timedelta(days=5), currency="USD", po_number=None, three_way_match_status="NOT_APPLICABLE", ai_duplicate_flag=False),
        ]
        for inv in invoices:
            db.add(inv)
        await db.flush()

        # 4. Customers & AR Invoices
        customers = [
            Customer(id=_id(), tenant_id=TENANT, customer_code="CST001", name="Stark Industries", legal_name="Stark Industries Global", email="finance@stark.com", phone="+1-212-555-3000", status=CustomerStatus.ACTIVE, credit_limit=500000.00, payment_terms_days=30, currency="USD", total_revenue_ytd=1250000.00, total_outstanding=150000.00, days_sales_outstanding=28, ai_churn_risk=0.05, aging_current=100000.00, aging_30=50000.00, aging_60=0.00, aging_90=0.00, aging_over_90=0.00),
            Customer(id=_id(), tenant_id=TENANT, customer_code="CST002", name="Wayne Enterprises", legal_name="Wayne Enterprises Inc", email="ap@wayne.corp", phone="+1-312-555-8888", status=CustomerStatus.ACTIVE, credit_limit=1000000.00, payment_terms_days=45, currency="USD", total_revenue_ytd=680000.00, total_outstanding=200000.00, days_sales_outstanding=42, ai_churn_risk=0.15, aging_current=150000.00, aging_30=0.00, aging_60=50000.00, aging_90=0.00, aging_over_90=0.00),
        ]
        for c in customers:
            db.add(c)
        await db.flush()

        customer_invoices = [
            CustomerInvoice(id=_id(), tenant_id=TENANT, invoice_number="INV-CST-1001", customer_id=customers[0].id, status=CustomerInvoiceStatus.SENT, subtotal=100000.00, total_amount=100000.00, tax_amount=0.00, balance_due=100000.00, invoice_date=date.today() - timedelta(days=12), due_date=date.today() + timedelta(days=18), currency="USD", dunning_level=0),
            CustomerInvoice(id=_id(), tenant_id=TENANT, invoice_number="INV-CST-1002", customer_id=customers[1].id, status=CustomerInvoiceStatus.OVERDUE, subtotal=50000.00, total_amount=50000.00, tax_amount=0.00, balance_due=50000.00, invoice_date=date.today() - timedelta(days=62), due_date=date.today() - timedelta(days=17), currency="USD", dunning_level=2),
        ]
        for cinv in customer_invoices:
            db.add(cinv)
        await db.flush()

        # 5. Budgets & Forecasts
        budget = Budget(
            id=_id(), tenant_id=TENANT, name="FY2026 R&D Budget", budget_type="OPEX",
            fiscal_year=2026, status=BudgetStatus.ACTIVE, total_planned=1200000.00,
            total_actual=485000.00, total_variance=715000.00, variance_pct=5.4,
            department="Engineering", owner_id="finance_agent"
        )
        db.add(budget)
        await db.flush()

        budget_lines = [
            BudgetLine(id=_id(), tenant_id=TENANT, budget_id=budget.id, account_id=gl_accounts[5].id, category="Hosting", period=1, period_label="Jan 2026", planned_amount=50000.00, actual_amount=52000.00, committed_amount=0.00, variance=-2000.00),
            BudgetLine(id=_id(), tenant_id=TENANT, budget_id=budget.id, account_id=gl_accounts[5].id, category="Hosting", period=2, period_label="Feb 2026", planned_amount=50000.00, actual_amount=48000.00, committed_amount=0.00, variance=2000.00),
            BudgetLine(id=_id(), tenant_id=TENANT, budget_id=budget.id, account_id=gl_accounts[7].id, category="Salaries", period=1, period_label="Jan 2026", planned_amount=100000.00, actual_amount=98000.00, committed_amount=0.00, variance=2000.00),
        ]
        for bl in budget_lines:
            db.add(bl)

        forecast = Forecast(
            id=_id(), tenant_id=TENANT, forecast_name="Q3 Cash Flow Projection", forecast_type="ROLLING",
            scenario="BASE", period_start=date(2026, 7, 1), period_end=date(2026, 9, 30),
            total_forecast=450000.00, confidence_score=0.92
        )
        db.add(forecast)
        await db.flush()

        # 6. Expense Reports
        # employee_id is an FK to hr_employees.id (a UUID) - use a real row.
        # The old hardcoded "EMP-001" was a dangling reference SQLite accepted
        # silently; Postgres rejected it and rolled back the whole domain seed.
        from sqlalchemy import select as _select
        from app.hr.models.core import HREmployee
        _emp = (await db.execute(
            _select(HREmployee.id).where(HREmployee.tenant_id == TENANT).limit(1)
        )).scalar_one_or_none()
        exp_report = ExpenseReport(
            id=_id(), tenant_id=TENANT, report_number="EXP-2026-004", title="Q1 Technical Sales Travel",
            employee_id=_emp, status=ExpenseReportStatus.PENDING_APPROVAL, total_amount=1240.00,
            approved_amount=0.00, currency="USD", ai_compliance_score=94.5,
            ai_policy_violations=[]
        )
        db.add(exp_report)
        await db.flush()

        expense_items = [
            ExpenseItem(id=_id(), tenant_id=TENANT, report_id=exp_report.id, line_number=1, expense_date=date.today() - timedelta(days=4), category=ExpenseCategory.TRAVEL, description="Flight SF to NYC", merchant="United Airlines", amount=850.00, receipt_path="/receipts/united-850.pdf", is_within_policy=True, is_billable=False),
            ExpenseItem(id=_id(), tenant_id=TENANT, report_id=exp_report.id, line_number=2, expense_date=date.today() - timedelta(days=3), category=ExpenseCategory.MEALS, description="Client dinner Stark Ind", merchant="Del Posto", amount=390.00, receipt_path="/receipts/delposto-390.pdf", is_within_policy=True, is_billable=True),
        ]
        for item in expense_items:
            db.add(item)
        await db.flush()

        # 7. Cash Flow (Treasury)
        cash_flows = [
            CashFlow(id=_id(), tenant_id=TENANT, flow_date=date.today() - timedelta(days=1), flow_type=CashFlowType.OPERATING_INFLOW, category="Customer Subscription", amount=12000.00, currency="USD", is_forecast=False, source_module="AR"),
            CashFlow(id=_id(), tenant_id=TENANT, flow_date=date.today() - timedelta(days=2), flow_type=CashFlowType.OPERATING_OUTFLOW, category="Hosting Bills", amount=-8200.00, currency="USD", is_forecast=False, source_module="AP"),
        ]
        for cf in cash_flows:
            db.add(cf)

        # 8. Tax Filings
        tax_filings = [
            TaxFiling(id=_id(), tenant_id=TENANT, filing_type="FEDERAL_INCOME", jurisdiction="US Federal - IRS", period="FY2025", fiscal_year=2025, status=FilingStatus.IN_PROGRESS, tax_liability=245000.00, tax_paid=0.00, due_date=date(2026, 7, 15), form_number="Form 1120"),
            TaxFiling(id=_id(), tenant_id=TENANT, filing_type="STATE_SALES", jurisdiction="State of California - CDTFA", period="Q1 2026", fiscal_year=2026, status=FilingStatus.FILED, tax_liability=18500.00, tax_paid=18500.00, due_date=date(2026, 4, 30), form_number="CDTFA-401"),
        ]
        for tf in tax_filings:
            db.add(tf)

        # 9. Reports (Reporting)
        reports = [
            FinancialReport(
                id=_id(), tenant_id=TENANT, report_type=ReportType.INCOME_STATEMENT,
                title="Q1 2026 Profit & Loss", status=ReportStatus.COMPLETED,
                period_start=date(2026, 1, 1), period_end=date(2026, 3, 31),
                generated_at=datetime.utcnow(),
                report_data={"net_income": 350000.00, "total_revenue": 1850000.00, "total_expenses": 1500000.00},
                summary={"net_income": 350000.00, "total_revenue": 1850000.00, "total_expenses": 1500000.00},
                ai_anomalies=[]
            ),
        ]
        for rep in reports:
            db.add(rep)

        # 10. Audit Findings & SOX Controls
        controls = [
            SOXControl(id=_id(), tenant_id=TENANT, control_id_code="SOX-AC-01", name="Journal Entry Approval Controls", description="Ensure all JEs over $10k have manager sign-off.", control_type="PREVENTATIVE", frequency="TRANSACTIONAL", nature="MANUAL", area="General Ledger", status=SOXControlStatus.EFFECTIVE, risk_level="HIGH", ai_effectiveness_score=98.5),
            SOXControl(id=_id(), tenant_id=TENANT, control_id_code="SOX-AP-03", name="Vendor Master Setup Controls", description="Verify W-9 is present for new vendors before invoice creation.", control_type="PREVENTATIVE", frequency="DAILY", nature="SYSTEM", area="Accounts Payable", status=SOXControlStatus.NEEDS_IMPROVEMENT, risk_level="MEDIUM", ai_effectiveness_score=68.0),
        ]
        for ctrl in controls:
            db.add(ctrl)
        await db.flush()

        findings = [
            AuditFinding(id=_id(), tenant_id=TENANT, finding_number="AUD-2026-001", title="Missing W-9 Documentation", severity=FindingSeverity.MEDIUM, status=FindingStatus.OPEN, area="Accounts Payable", description="3 new vendors added without verified W-9 documents on file.", financial_impact=0.00, remediation_owner="AP Lead", remediation_plan="Reach out to vendors to collect W-9 documents and implement hard blocker in system.", ai_detected=True),
        ]
        for find in findings:
            db.add(find)

        # 11. Compliance Rules
        rules = [
            FinanceComplianceRule(id=_id(), tenant_id=TENANT, regulation="GAAP", section="ASC 606", name="Revenue Recognition Contract Assets", description="Revenue from SaaS contracts must be recognized straight-line over contract term.", severity="CRITICAL", is_blocking=True, applies_to="CustomerInvoice"),
            FinanceComplianceRule(id=_id(), tenant_id=TENANT, regulation="SOX", section="Section 404", name="Double Entry Balance Check", description="Debits must equal Credits for all approved Journal Entries.", severity="CRITICAL", is_blocking=True, applies_to="JournalEntry"),
        ]
        for ru in rules:
            db.add(ru)

        await db.commit()
        print("[SUCCESS] Seeded Finance database:")
        print(f"   - {len(gl_accounts)} GL accounts")
        print(f"   - {len(vendors)} vendors, {len(invoices)} bills")
        print(f"   - {len(customers)} customers, {len(customer_invoices)} customer invoices")
        print(f"   - {len(controls)} SOX controls, {len(findings)} audit findings")
        print(f"   - {len(rules)} compliance rules")

if __name__ == "__main__":
    asyncio.run(seed())
