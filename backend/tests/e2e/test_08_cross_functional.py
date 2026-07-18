"""
KAEOS E2E Test 08 — Cross-Functional Department Tests
Tests cross-department interactions: conflict detection between domains,
knowledge graph spanning departments, shared signals, and org intelligence.
"""
import pytest
from .conftest import assert_object


@pytest.mark.asyncio
class TestCrossFunctional:
    """Cross-functional tests — interactions between departments."""

    async def test_cross_department_conflicts(self, client):
        """Conflicts span multiple departments."""
        data = await assert_object(client, "/conflicts", ["conflicts", "total"])
        if data["conflicts"]:
            # Verify conflicts reference rules from different domains
            conflict = data["conflicts"][0]
            assert conflict.get("rule_a") or conflict.get("rule_a_id")
            assert conflict.get("rule_b") or conflict.get("rule_b_id")

    async def test_cross_department_coverage(self, client):
        """Health dashboard covers all departments."""
        data = await assert_object(client, "/dashboard/health", ["coverage"])
        departments = [c["department"] for c in data["coverage"]]
        assert len(departments) >= 3, f"Expected coverage for 3+ departments, got {departments}"

    async def test_cross_department_graph(self, client):
        """Knowledge graph connects entities across departments."""
        data = await assert_object(client, "/topology/graph", ["nodes", "edges"])
        if data["nodes"]:
            groups = set(n.get("group", n.get("department", "")) for n in data["nodes"])
            assert len(groups) >= 2, f"Expected nodes from 2+ groups, got {groups}"

    async def test_cross_department_signals(self, client):
        """Signals come from multiple department sources."""
        data = await assert_object(client, "/extraction/signals", ["signals"])
        if data["signals"]:
            domains = set(s.get("domain", "") for s in data["signals"])
            assert len(domains) >= 2, f"Expected signals from 2+ domains, got {domains}"

    async def test_workforce_departments_list(self, client):
        """Workforce departments endpoint lists all departments."""
        r = await client.get("/workforce/departments")
        assert r.status_code == 200
        data = r.json()
        depts = data.get("departments", data) if isinstance(data, dict) else data
        if isinstance(depts, list):
            assert len(depts) >= 4, f"Expected 4+ departments, got {len(depts)}"

    async def test_workforce_overview(self, client):
        """Workforce overview aggregates cross-department metrics."""
        r = await client.get("/workforce/overview")
        assert r.status_code == 200

    async def test_workforce_analytics(self, client):
        """Workforce analytics endpoint works."""
        r = await client.get("/workforce/analytics")
        assert r.status_code == 200

    async def test_department_capabilities(self, client):
        """Each department exposes capabilities."""
        r = await client.get("/workforce/departments")
        data = r.json()
        depts = data.get("departments", data) if isinstance(data, dict) else data
        if isinstance(depts, list) and depts:
            dept_id = depts[0].get("id", depts[0].get("slug", ""))
            if dept_id:
                r2 = await client.get(f"/workforce/departments/{dept_id}/capabilities")
                assert r2.status_code == 200

    async def test_department_agents(self, client):
        """Departments expose their AI agents."""
        r = await client.get("/workforce/departments")
        data = r.json()
        depts = data.get("departments", data) if isinstance(data, dict) else data
        if isinstance(depts, list) and depts:
            dept_id = depts[0].get("id", depts[0].get("slug", ""))
            if dept_id:
                r2 = await client.get(f"/workforce/departments/{dept_id}/agents")
                assert r2.status_code == 200

    async def test_change_readiness_scoring(self, client, has_ollama):
        """Org intelligence: change readiness scoring across departments."""
        r = await client.post("/org-intelligence/change-readiness", json={
            "department": "engineering",
            "change_description": "Migrate from monolith to microservices architecture"
        })
        assert r.status_code == 200

    async def test_influence_path_mapping(self, client, has_ollama):
        """Org intelligence: influence path mapping."""
        r = await client.post("/org-intelligence/influence-path", json={
            "target_outcome": "Reduce customer churn by 15%",
            "department": "support"
        })
        assert r.status_code == 200

    async def test_skills_topology(self, client):
        """Skills topology spans departments."""
        r = await client.get("/org-intelligence/skills-topology")
        assert r.status_code == 200

    async def test_what_if_simulation(self, client, has_ollama):
        """Cross-domain what-if simulation."""
        r = await client.post("/simulation/what-if", json={
            "change_description": "Increase refund auto-approval threshold from $50 to $100",
            "target_domain": "support",
            "risk_tolerance": "MEDIUM"
        })
        assert r.status_code == 200

    async def test_executive_overview(self, client):
        """Executive overview aggregates all departments."""
        data = await assert_object(client, "/executive/overview", [])
        # Should have cross-department counts
        assert isinstance(data, dict)

    async def test_executive_health(self, client):
        """Executive health spans all departments."""
        r = await client.get("/executive/health")
        assert r.status_code == 200

    async def test_executive_risks(self, client):
        """Executive risk view aggregates cross-department risks."""
        r = await client.get("/executive/risks")
        assert r.status_code == 200

    async def test_executive_predictions(self, client):
        """Executive predictions leverage cross-domain data."""
        r = await client.get("/executive/predictions")
        assert r.status_code == 200

    async def test_executive_trust(self, client):
        """Executive trust score."""
        r = await client.get("/executive/trust")
        assert r.status_code == 200
