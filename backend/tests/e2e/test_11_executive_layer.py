"""
KAEOS E2E Test 11 — Executive Layer
Tests executive cockpit, command center, digital twin, predictive ops,
OODA monitor, and reality experience.
"""
import pytest
from .conftest import assert_dashboard


@pytest.mark.asyncio
class TestExecutiveLayer:
    """Executive Layer — cockpit, command center, digital twin."""

    async def test_executive_overview(self, client):
        """Executive overview aggregates all domains."""
        await assert_dashboard(client, "/executive/overview")

    async def test_executive_health(self, client):
        """Executive health summary."""
        r = await client.get("/executive/health")
        assert r.status_code == 200

    async def test_executive_risks(self, client):
        """Executive risk analysis."""
        r = await client.get("/executive/risks")
        assert r.status_code == 200

    async def test_executive_predictions(self, client):
        """Executive predictive analytics."""
        r = await client.get("/executive/predictions")
        assert r.status_code == 200

    async def test_executive_trust_score(self, client):
        """Executive trust score."""
        r = await client.get("/executive/trust")
        assert r.status_code == 200

    async def test_cockpit(self, client):
        """Executive cockpit (rolling intelligence)."""
        r = await client.get("/dashboard/cockpit")
        assert r.status_code == 200

    async def test_activity_feed(self, client):
        """Activity feed returns recent system events."""
        r = await client.get("/agents/activity-feed?limit=15")
        assert r.status_code == 200
        data = r.json()
        events = data.get("events", [])
        assert isinstance(events, list)

    async def test_health_report(self, client):
        """System health report."""
        r = await client.get("/reports/health")
        assert r.status_code == 200

    async def test_compliance_report(self, client):
        """System compliance report."""
        r = await client.get("/reports/compliance")
        assert r.status_code == 200

    async def test_digital_twin(self, client):
        """Reality/digital twin returns org graph."""
        r = await client.get("/reality/twin")
        assert r.status_code == 200
        data = r.json()
        assert "nodes" in data, "Twin should return nodes"

    async def test_digital_twin_shock(self, client, has_ollama):
        """Shock simulation on digital twin."""
        r = await client.post("/reality/shock", json={
            "shock_type": "BUDGET_CUT",
            "target_id": "engineering",
            "severity": 0.3,
        })
        assert r.status_code == 200

    async def test_provenance_feed(self, client):
        """Provenance feed for reality experience."""
        r = await client.get("/reality/provenance")
        assert r.status_code == 200

    async def test_learning_stats(self, client):
        """Learning stats for reality experience."""
        r = await client.get("/reality/learning")
        assert r.status_code == 200

    async def test_ooda_events(self, client):
        """OODA cognitive loop events."""
        r = await client.get("/dashboard/ooda-events")
        assert r.status_code == 200

    async def test_webhooks_list(self, client):
        """Webhooks subscriptions list."""
        r = await client.get("/webhooks")
        assert r.status_code == 200
        data = r.json()
        # Returns list or dict with webhooks or subscriptions key
        webhooks = data.get("webhooks", data.get("subscriptions", data)) if isinstance(data, dict) else data
        assert isinstance(webhooks, list)

    async def test_event_log(self, client):
        """System event log."""
        r = await client.get("/events/log?limit=30")
        assert r.status_code == 200
        data = r.json()
        events = data.get("events", data) if isinstance(data, dict) else data
        assert isinstance(events, list)

    async def test_tenant_stats(self, client):
        """Multi-tenant stats. Cross-tenant enumeration is a platform-admin
        operation gated on X-Admin-Secret (a plain call correctly 403s)."""
        import os
        secret = os.environ.get("ADMIN_SECRET", "")
        if not secret:
            pytest.skip("ADMIN_SECRET not set in the test environment")
        r = await client.get("/tenants/stats", headers={"X-Admin-Secret": secret})
        assert r.status_code == 200, f"{r.status_code}: {r.text[:200]}"

    async def test_executive_story(self, client):
        """Executive narrative story endpoint."""
        r = await client.get("/executive/story")
        assert r.status_code == 200
        data = r.json()
        assert "story" in data

    async def test_search_global(self, client):
        """Global search endpoint."""
        r = await client.get("/search?q=compliance")
        assert r.status_code == 200
