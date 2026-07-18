"""
KAEOS E2E Test 05 — Sales Department
Tests Sales-specific endpoints: leads, accounts, opportunities,
forecasts, dashboard, and AI agents.
"""
import pytest
from .conftest import assert_dashboard, skip_if_llm_outage


@pytest.mark.asyncio
class TestSalesDepartment:
    """Sales Department — pipeline, forecasting, account management."""

    async def test_sales_dashboard(self, client):
        """Sales dashboard returns aggregate metrics."""
        await assert_dashboard(client, "/sales/dashboard")

    async def test_sales_leads(self, client):
        """Leads list returns seeded leads."""
        r = await client.get("/sales/leads")
        assert r.status_code == 200
        leads = r.json()
        assert isinstance(leads, list)
        assert len(leads) > 0, "Expected seeded sales leads"

    async def test_sales_lead_scoring_agent(self, client, has_ollama):
        """Lead scoring AI agent runs on a lead (uses real Ollama)."""
        leads = (await client.get("/sales/leads")).json()
        if not leads:
            pytest.skip("No leads to score")
        r = await client.post(f"/sales/leads/{leads[0]['id']}/score")
        assert r.status_code == 200

    async def test_sales_accounts(self, client):
        """Accounts list returns seeded accounts."""
        r = await client.get("/sales/accounts")
        assert r.status_code == 200
        accounts = r.json()
        assert isinstance(accounts, list)
        assert len(accounts) > 0, "Expected seeded accounts"

    async def test_sales_account_health_agent(self, client, has_ollama):
        """Account health AI agent."""
        accounts = (await client.get("/sales/accounts")).json()
        if not accounts:
            pytest.skip("No accounts")
        r = await client.post(f"/sales/accounts/{accounts[0]['id']}/health")
        assert r.status_code == 200

    async def test_sales_opportunities(self, client):
        """Opportunities list returns seeded pipeline."""
        r = await client.get("/sales/opportunities")
        assert r.status_code == 200
        opps = r.json()
        assert isinstance(opps, list)
        assert len(opps) > 0, "Expected seeded opportunities"

    async def test_sales_pipeline_agent(self, client, has_ollama):
        """Pipeline coaching AI agent."""
        opps = (await client.get("/sales/opportunities")).json()
        if not opps:
            pytest.skip("No opportunities")
        r = await client.post(f"/sales/opportunities/{opps[0]['id']}/coach")
        assert r.status_code == 200

    async def test_sales_forecasts(self, client):
        """Forecasts list returns seeded forecasts."""
        r = await client.get("/sales/forecasts")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    async def test_sales_forecast_agent(self, client, has_ollama):
        """Forecast prediction AI agent."""
        forecasts = (await client.get("/sales/forecasts")).json()
        if not forecasts:
            pytest.skip("No forecasts")
        r = await client.post(f"/sales/forecasts/{forecasts[0]['id']}/predict")
        skip_if_llm_outage(r)
        assert r.status_code == 200
