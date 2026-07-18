"""
KAEOS E2E Test 01 — Company Brain
Tests the core knowledge layer: brain overview, rules, topology graph,
elicitation, provenance, extraction signals, and search.
"""
import pytest
from .conftest import assert_object


@pytest.mark.asyncio
class TestCompanyBrain:
    """Company Brain — the enterprise's single source of truth."""

    async def test_brain_overview(self, client):
        """Brain overview returns aggregated intelligence stats."""
        data = await assert_object(client, "/brain/overview", [
            "total_rules", "total_skills", "total_executions",
            "departments", "processes",
        ])
        assert data["total_rules"] > 0, "Expected seeded rules"
        assert data["total_skills"] > 0, "Expected seeded skills"

    async def test_dashboard_health(self, client):
        """KB Health dashboard returns all health metrics."""
        data = await assert_object(client, "/dashboard/health", [
            "overall_score", "total_rules", "total_skills",
            "coverage", "confidence_distribution", "freshness",
            "agent_metrics", "elicitation_metrics",
        ])
        assert 0 <= data["overall_score"] <= 100
        assert len(data["coverage"]) > 0, "Expected department coverage data"

    async def test_rules_list(self, client):
        """Rules endpoint returns seeded rules."""
        data = await assert_object(client, "/rules", ["total", "rules"])
        assert data["total"] > 0
        assert len(data["rules"]) > 0
        # Validate rule shape
        rule = data["rules"][0]
        assert "id" in rule
        assert "statement" in rule
        assert "confidence_scalar" in rule
        assert "domain" in rule

    async def test_rules_filter_by_domain(self, client):
        """Rules can be filtered by domain."""
        r = await client.get("/rules?domain=support")
        assert r.status_code == 200
        data = r.json()
        for rule in data["rules"]:
            assert rule["domain"] == "support"

    async def test_rule_detail(self, client):
        """Can fetch individual rule with provenance."""
        rules_resp = await client.get("/rules")
        rules = rules_resp.json()["rules"]
        if rules:
            rule_id = rules[0]["id"]
            r = await client.get(f"/rules/{rule_id}")
            assert r.status_code == 200
            assert r.json()["id"] == rule_id

    async def test_rule_provenance(self, client):
        """Provenance chain exists for rules (200) or is empty (404 — no provenance seeded)."""
        rules_resp = await client.get("/rules")
        rules = rules_resp.json()["rules"]
        if rules:
            rule_id = rules[0]["id"]
            r = await client.get(f"/rules/{rule_id}/provenance")
            # 200 = provenance exists; 404 = no provenance seeded yet; both are valid
            assert r.status_code in (200, 404), \
                f"Unexpected status {r.status_code}: {r.text[:200]}"

    async def test_topology_graph(self, client):
        """Knowledge graph returns nodes and edges."""
        data = await assert_object(client, "/topology/graph", ["nodes", "edges"])
        assert len(data["nodes"]) > 0, "Expected graph nodes from seeded data"

    async def test_elicitation_dashboard(self, client):
        """Elicitation dashboard returns pending questions and contributors."""
        await assert_object(client, "/elicitation/dashboard", [
            "pending_questions", "contributors",
        ])

    async def test_extraction_signals(self, client):
        """Extraction pipeline returns ingested signals."""
        await assert_object(client, "/extraction/signals", ["signals"])

    async def test_extraction_candidates(self, client):
        """Extraction pipeline returns candidate rules."""
        await assert_object(client, "/extraction/candidates", ["candidates"])

    async def test_compliance_dashboard(self, client):
        """Compliance dashboard returns framework coverage."""
        await assert_object(client, "/dashboard/compliance", [
            "frameworks", "total_tagged_rules",
        ])

    async def test_provenance_global_ledger(self, client):
        """Global provenance ledger is accessible."""
        r = await client.get("/provenance/global/ledger")
        assert r.status_code == 200

    async def test_global_search(self, client):
        """Global search returns results."""
        r = await client.get("/search?q=refund")
        assert r.status_code == 200

    async def test_ooda_events(self, client):
        """OODA cognitive loop events are accessible."""
        r = await client.get("/dashboard/ooda-events")
        assert r.status_code == 200

    async def test_cockpit(self, client):
        """Executive cockpit aggregation endpoint works."""
        r = await client.get("/dashboard/cockpit")
        assert r.status_code == 200

    @pytest.mark.ollama
    async def test_benchmark_network(self, client):
        """Benchmark network returns comparison data."""
        await assert_object(client, "/benchmark/network", [
            "local_org", "industry_median", "department_benchmarks",
        ])

    async def test_connectors_list(self, client):
        """Connectors list returns seeded connectors."""
        data = await assert_object(client, "/connectors", ["connectors", "stats"])
        assert len(data["connectors"]) > 0
        assert data["stats"]["total"] > 0

    async def test_conflicts_list(self, client):
        """Conflicts endpoint returns seeded conflicts."""
        await assert_object(client, "/conflicts", ["conflicts", "total"])

    async def test_marketplace_templates(self, client):
        """Marketplace returns knowledge templates."""
        data = await assert_object(client, "/marketplace", ["templates", "total"])
        assert data["total"] > 0

    async def test_security_audit_log(self, client):
        """Security fabric returns audit logs."""
        await assert_object(client, "/security/audit-log", ["logs", "stats"])

    async def test_redteam_scans(self, client):
        """Red team harness returns scan results."""
        await assert_object(client, "/redteam/scans/recent", ["scans", "summary"])
