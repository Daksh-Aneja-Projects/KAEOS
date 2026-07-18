"""
KAEOS E2E Test 03 — Finance Department
Tests Finance-specific endpoints: vendors, invoices, payments, budgets,
cash flow, tax, audit, SOX controls, and AP/AR agents.
"""
import pytest
from .conftest import assert_dashboard


@pytest.mark.asyncio
class TestFinanceDepartment:
    """Finance Department — AP, AR, treasury, budgeting, compliance."""

    async def test_finance_dashboard(self, client):
        """Finance dashboard returns aggregate metrics."""
        await assert_dashboard(client, "/finance/dashboard")

    async def test_finance_vendors(self, client):
        """Vendors list returns seeded vendors."""
        r = await client.get("/finance/vendors")
        assert r.status_code == 200
        vendors = r.json()
        assert isinstance(vendors, list)
        assert len(vendors) > 0, "Expected seeded vendors"

    async def test_finance_invoices(self, client):
        """Invoices list returns seeded invoices."""
        r = await client.get("/finance/invoices")
        assert r.status_code == 200
        invoices = r.json()
        assert isinstance(invoices, list)
        assert len(invoices) > 0, "Expected seeded invoices"

    async def test_finance_payments(self, client):
        """Payments list returns seeded payments."""
        r = await client.get("/finance/payments")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    async def test_finance_customers(self, client):
        """Customers list returns seeded customers."""
        r = await client.get("/finance/customers")
        assert r.status_code == 200
        assert isinstance(r.json(), list)
        assert len(r.json()) > 0

    async def test_finance_receivables(self, client):
        """Receivables list returns seeded AR data."""
        r = await client.get("/finance/receivables")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    async def test_finance_budgets(self, client):
        """Budgets list returns seeded budgets."""
        r = await client.get("/finance/budgets")
        assert r.status_code == 200
        budgets = r.json()
        assert isinstance(budgets, list)
        assert len(budgets) > 0, "Expected seeded budgets"

    async def test_finance_budget_lines(self, client):
        """Budget detail returns line items."""
        budgets = (await client.get("/finance/budgets")).json()
        if budgets:
            budget_id = budgets[0]["id"]
            r = await client.get(f"/finance/budgets/{budget_id}/lines")
            assert r.status_code == 200

    async def test_finance_forecasts(self, client):
        """Forecasts endpoint returns data."""
        r = await client.get("/finance/forecasts")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    async def test_finance_expense_reports(self, client):
        """Expense reports list returns seeded data."""
        r = await client.get("/finance/expense-reports")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    async def test_finance_bank_accounts(self, client):
        """Treasury bank accounts list."""
        r = await client.get("/finance/bank-accounts")
        assert r.status_code == 200
        accounts = r.json()
        assert isinstance(accounts, list)
        assert len(accounts) > 0

    async def test_finance_cash_flow(self, client):
        """Cash flow records."""
        r = await client.get("/finance/cash-flow")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    async def test_finance_tax_filings(self, client):
        """Tax filings list."""
        r = await client.get("/finance/tax/filings")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    async def test_finance_tax_rules(self, client):
        """Tax rules list."""
        r = await client.get("/finance/tax/rules")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    async def test_finance_reports(self, client):
        """Financial reports list."""
        r = await client.get("/finance/reports")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    async def test_finance_audit_findings(self, client):
        """Audit findings list."""
        r = await client.get("/finance/audit/findings")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    async def test_finance_sox_controls(self, client):
        """SOX controls list."""
        r = await client.get("/finance/sox-controls")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    async def test_finance_compliance_rules(self, client):
        """Finance compliance rules."""
        r = await client.get("/finance/compliance-rules")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    async def test_finance_ap_agent(self, client, has_ollama):
        """AP matching agent runs on an invoice (uses real Ollama)."""
        invoices = (await client.get("/finance/invoices")).json()
        if not invoices:
            pytest.skip("No invoices to process")
        inv_id = invoices[0]["id"]
        r = await client.post(f"/finance/invoices/{inv_id}/match")
        assert r.status_code == 200
