"""
KAEOS E2E Test 06 — Support Department
Tests Support-specific endpoints: tickets, KB articles, CSAT surveys,
SLA metrics, dashboard, and AI agents (triage, resolution, escalation).
"""
import pytest
from .conftest import assert_dashboard, skip_if_llm_outage


@pytest.mark.asyncio
class TestSupportDepartment:
    """Support Department — tickets, SLA, CSAT, knowledge base."""

    async def test_support_dashboard(self, client):
        """Support dashboard returns aggregate metrics."""
        await assert_dashboard(client, "/support/dashboard")

    async def test_support_tickets(self, client):
        """Tickets list returns seeded tickets."""
        r = await client.get("/support/tickets")
        assert r.status_code == 200
        tickets = r.json()
        assert isinstance(tickets, list)
        assert len(tickets) > 0, "Expected seeded support tickets"

    async def test_support_triage_agent(self, client, has_ollama):
        """Triage AI agent classifies a ticket (uses real Ollama)."""
        tickets = (await client.get("/support/tickets")).json()
        if not tickets:
            pytest.skip("No tickets")
        r = await client.post(f"/support/tickets/{tickets[0]['id']}/triage")
        assert r.status_code == 200

    async def test_support_resolution_agent(self, client, has_ollama):
        """Resolution AI agent processes a ticket."""
        tickets = (await client.get("/support/tickets")).json()
        if not tickets:
            pytest.skip("No tickets")
        r = await client.post(f"/support/tickets/{tickets[0]['id']}/solve")
        assert r.status_code == 200

    async def test_support_escalation_agent(self, client, has_ollama):
        """Escalation AI agent."""
        tickets = (await client.get("/support/tickets")).json()
        if not tickets:
            pytest.skip("No tickets")
        r = await client.post(f"/support/tickets/{tickets[0]['id']}/escalate")
        skip_if_llm_outage(r)
        assert r.status_code == 200

    async def test_support_kb_articles(self, client):
        """KB articles list."""
        r = await client.get("/support/kb/articles")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    async def test_support_csat_surveys(self, client):
        """CSAT surveys list."""
        r = await client.get("/support/csat/surveys")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    async def test_support_feedback_agent(self, client, has_ollama):
        """Feedback analysis AI agent."""
        surveys = (await client.get("/support/csat/surveys")).json()
        if not surveys:
            pytest.skip("No surveys")
        r = await client.post(f"/support/csat/{surveys[0]['id']}/analyze")
        assert r.status_code == 200

    async def test_support_sla_metrics(self, client):
        """SLA metrics list."""
        r = await client.get("/support/sla/metrics")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    async def test_support_sla_check_agent(self, client, has_ollama):
        """SLA compliance check agent."""
        r = await client.post("/support/sla/check")
        skip_if_llm_outage(r)
        assert r.status_code == 200
