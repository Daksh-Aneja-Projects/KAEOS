"""Finance analytics insights must never contain an em-dash (UI copy standard).

Regression for the two insight strings in app.finance.services.analytics that
used to read 'flag — review before payment.' and 'position — check the
payment run schedule.'; both branches are exercised here.
"""
from datetime import date, timedelta

from app.finance.models.accounts_payable import Invoice, InvoiceStatus, Vendor
from app.finance.models.treasury import BankAccount
from app.finance.services.analytics import finance_analytics

TENANT = "tenant_fin_analytics_emdash"


async def test_analytics_insights_have_no_em_dash(db):
    today = date.today()
    vendor = Vendor(tenant_id=TENANT, vendor_code="V1", name="Acme Supplies")
    db.add(vendor)
    await db.flush()

    # Duplicate-flag branch + overdue payables exceeding cash: exercises both
    # insight messages that used to carry an em-dash.
    db.add(Invoice(
        tenant_id=TENANT, vendor_id=vendor.id, invoice_number="INV-EMD-1",
        invoice_date=today - timedelta(days=40), due_date=today - timedelta(days=10),
        status=InvoiceStatus.OVERDUE, subtotal=5000, total_amount=5000,
        balance_due=5000, ai_duplicate_flag=True,
    ))
    db.add(BankAccount(
        tenant_id=TENANT, account_name="Ops Checking", bank_name="Test Bank",
        account_number_masked="****0001", current_balance=100,
    ))
    await db.commit()

    result = await finance_analytics(db, TENANT)
    assert result["insights"], "expected at least one insight"
    for insight in result["insights"]:
        assert "—" not in insight["message"], insight["message"]

    messages = " ".join(i["message"] for i in result["insights"])
    assert "duplicate flag" in messages
    assert "Open payables exceed" in messages
