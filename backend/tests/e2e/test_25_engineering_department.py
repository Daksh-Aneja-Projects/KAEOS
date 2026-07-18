"""
KAEOS E2E Test 25 — Engineering & IT Ops Department

The largest slice of enterprise AI spend (coding ~55%, IT ops ~10%) and the
last major function KAEOS did not model. Covers the service catalog, delivery
surface, incidents, and the three gated agents — including the two behaviours
that must never regress:

  * the incident agent may only blame a deploy that actually SHIPPED and
    preceded detection (it once recommended rolling back a pending deploy);
  * the deploy-risk agent must never self-approve a production release.
"""
import pytest

from .conftest import assert_dashboard, skip_if_llm_outage


@pytest.mark.asyncio
class TestEngineeringCatalog:
    """Service catalog, engineers, and the live DORA dashboard."""

    async def test_dashboard(self, client):
        data = await assert_dashboard(client, "/engineering/dashboard")
        for key in ("total_services", "open_pull_requests", "open_incidents",
                    "change_failure_rate_pct", "mttr_minutes", "engineers_on_call"):
            assert key in data, f"Missing '{key}'. Keys: {list(data)}"
        assert data["total_services"] >= 1, "Expected seeded services"

    async def test_dashboard_metrics_are_derived_not_hardcoded(self, client):
        """Change-failure rate must reconcile with the deployments actually stored."""
        dash = (await client.get("/engineering/dashboard")).json()
        deploys = (await client.get("/engineering/deployments")).json()
        if not deploys:
            pytest.skip("No deployments seeded")
        failed = [d for d in deploys if d["status"] in ("FAILED", "ROLLED_BACK")]
        expected = round(len(failed) / len(deploys) * 100, 1)
        assert dash["change_failure_rate_pct"] == expected, (
            f"Dashboard reports {dash['change_failure_rate_pct']}% but deployments imply {expected}%"
        )

    async def test_services_list(self, client):
        r = await client.get("/engineering/services")
        assert r.status_code == 200
        services = r.json()
        assert isinstance(services, list) and services
        for key in ("id", "name", "tier", "health", "error_budget_remaining_pct"):
            assert key in services[0]

    async def test_service_detail_and_404(self, client):
        services = (await client.get("/engineering/services")).json()
        sid = services[0]["id"]
        r = await client.get(f"/engineering/services/{sid}")
        assert r.status_code == 200
        assert r.json()["id"] == sid

        missing = await client.get("/engineering/services/not-a-service")
        assert missing.status_code == 404

    async def test_services_filter_by_health(self, client):
        r = await client.get("/engineering/services?health=HEALTHY")
        assert r.status_code == 200
        assert all(s["health"] == "HEALTHY" for s in r.json())

    async def test_engineers_list(self, client):
        r = await client.get("/engineering/engineers")
        assert r.status_code == 200
        engineers = r.json()
        assert isinstance(engineers, list) and engineers
        assert "on_call" in engineers[0] and "squad" in engineers[0]


@pytest.mark.asyncio
class TestDeliverySurface:
    """Pull requests and deployments."""

    async def test_pull_requests_list(self, client):
        r = await client.get("/engineering/pull-requests")
        assert r.status_code == 200
        prs = r.json()
        assert isinstance(prs, list) and prs
        for key in ("number", "title", "status", "files_changed", "ci_passing"):
            assert key in prs[0]

    async def test_pull_requests_filter_by_status(self, client):
        r = await client.get("/engineering/pull-requests?status=MERGED")
        assert r.status_code == 200
        assert all(p["status"] == "MERGED" for p in r.json())

    async def test_deployments_list(self, client):
        r = await client.get("/engineering/deployments")
        assert r.status_code == 200
        deploys = r.json()
        assert isinstance(deploys, list) and deploys
        for key in ("version", "environment", "status"):
            assert key in deploys[0]

    async def test_postmortems_list(self, client):
        r = await client.get("/engineering/postmortems")
        assert r.status_code == 200
        pms = r.json()
        assert isinstance(pms, list)
        if pms:
            assert "root_cause" in pms[0] and isinstance(pms[0]["action_items"], list)


@pytest.mark.asyncio
class TestIncidents:
    """Incident surface."""

    async def test_incidents_list(self, client):
        r = await client.get("/engineering/incidents")
        assert r.status_code == 200
        incidents = r.json()
        assert isinstance(incidents, list) and incidents
        for key in ("number", "title", "severity", "status", "customer_impacting"):
            assert key in incidents[0]

    async def test_incident_detail_and_404(self, client):
        incidents = (await client.get("/engineering/incidents")).json()
        r = await client.get(f"/engineering/incidents/{incidents[0]['id']}")
        assert r.status_code == 200
        missing = await client.get("/engineering/incidents/not-an-incident")
        assert missing.status_code == 404

    async def test_incidents_filter_by_severity(self, client):
        r = await client.get("/engineering/incidents?severity=SEV1")
        assert r.status_code == 200
        assert all(i["severity"] == "SEV1" for i in r.json())


@pytest.mark.asyncio
class TestEngineeringAgents:
    """The three gated AI agents."""

    async def test_code_review_agent(self, client, has_ollama):
        prs = (await client.get("/engineering/pull-requests")).json()
        risky = next((p for p in prs if p["touches_auth"] or not p["ci_passing"]), prs[0])

        r = await client.post(f"/engineering/pull-requests/{risky['id']}/review")
        skip_if_llm_outage(r)
        assert r.status_code == 200, f"review failed: {r.text[:300]}"
        data = r.json()
        assert data["risk_level"] in ("LOW", "MEDIUM", "HIGH", "CRITICAL")
        assert data["summary"]

        # A PR touching auth with red CI must never be assessed as low risk.
        if risky["touches_auth"] and not risky["ci_passing"]:
            assert data["risk_level"] in ("HIGH", "CRITICAL"), (
                f"auth change with failing CI assessed {data['risk_level']}"
            )

        # The assessment must persist onto the PR.
        refreshed = (await client.get("/engineering/pull-requests")).json()
        match = next(p for p in refreshed if p["id"] == risky["id"])
        assert match["ai_risk_level"] is not None

    async def test_code_review_unknown_pr_404(self, client):
        r = await client.post("/engineering/pull-requests/not-a-pr/review")
        assert r.status_code == 404

    async def test_incident_triage_correlates_only_shipped_prior_deploys(self, client, has_ollama):
        """
        Regression: the agent must not blame a deploy that never shipped or that
        started after detection. It once recommended rolling back a
        PENDING_APPROVAL release.
        """
        incidents = (await client.get("/engineering/incidents")).json()
        live = next((i for i in incidents if i["status"] not in ("RESOLVED", "CLOSED")), incidents[0])

        r = await client.post(f"/engineering/incidents/{live['id']}/triage")
        skip_if_llm_outage(r)
        assert r.status_code == 200, f"triage failed: {r.text[:300]}"
        data = r.json()
        assert data["severity"] in ("SEV1", "SEV2", "SEV3", "SEV4")
        assert data["probable_cause"] and data["recommended_action"]

        correlated = data.get("correlated_deployment")
        if correlated:
            deploys = (await client.get("/engineering/deployments")).json()
            match = next((d for d in deploys if d["version"] == correlated), None)
            assert match is not None, f"correlated a non-existent deploy: {correlated}"
            assert match["status"] != "PENDING_APPROVAL", (
                f"correlated deploy {correlated} never shipped — cannot have caused the incident"
            )
            assert match["started_at"] <= live["detected_at"], (
                f"correlated deploy {correlated} started after the incident was detected"
            )

    async def test_incident_triage_unknown_404(self, client):
        r = await client.post("/engineering/incidents/not-an-incident/triage")
        assert r.status_code == 404

    async def test_deploy_risk_agent_never_self_approves(self, client, has_ollama):
        """Production deploys are always-HITL: the agent produces evidence, not approval."""
        deploys = (await client.get("/engineering/deployments")).json()
        pending = next((d for d in deploys if d["status"] == "PENDING_APPROVAL"), deploys[0])

        r = await client.post(f"/engineering/deployments/{pending['id']}/assess")
        skip_if_llm_outage(r)
        assert r.status_code == 200, f"assess failed: {r.text[:300]}"
        data = r.json()

        assert data["requires_human_approval"] is True
        assert data["status"] == "PENDING_HITL", (
            f"deploy approval must gate to a human, got status={data['status']}"
        )
        assert 0 <= data["risk_score"] <= 100
        assert data["rationale"]

    async def test_deploy_risk_scores_degraded_tier1_higher(self, client, has_ollama):
        """Risk scoring must reflect real service posture, not be a constant."""
        deploys = (await client.get("/engineering/deployments")).json()
        services = {s["id"]: s for s in (await client.get("/engineering/services")).json()}

        scored = []
        for d in deploys[:3]:
            r = await client.post(f"/engineering/deployments/{d['id']}/assess")
            skip_if_llm_outage(r)
            if r.status_code == 200:
                svc = services.get(d["service_id"], {})
                scored.append((svc.get("tier"), svc.get("health"), r.json()["risk_score"]))

        if len(scored) < 2:
            pytest.skip("Not enough deployments scored to compare")
        risky = [s for s in scored if s[0] == "TIER_1" and s[1] != "HEALTHY"]
        safe = [s for s in scored if s[0] == "TIER_3"]
        if risky and safe:
            assert risky[0][2] > safe[0][2], (
                f"degraded tier-1 deploy ({risky[0][2]}) must outscore tier-3 ({safe[0][2]})"
            )

    async def test_deploy_assess_unknown_404(self, client):
        r = await client.post("/engineering/deployments/not-a-deploy/assess")
        assert r.status_code == 404
