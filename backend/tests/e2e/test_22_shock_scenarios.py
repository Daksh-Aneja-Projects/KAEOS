"""
KAEOS E2E Test 22 — M&A and Cyber-Incident Shock Scenarios
Tests the tuned causal shock models: merger integration and cyber incident
produce scenario-specific decision options with distinct cost/risk shapes,
and the physics engine models both as feature interventions.
"""
import pytest


async def _target_dept(client):
    twin = (await client.get("/reality/twin")).json()
    depts = [n for n in twin.get("nodes", []) if n.get("label") == "Department"]
    assert depts, "Twin has no department nodes"
    return depts[0]["id"]


@pytest.mark.asyncio
class TestMergerShock:
    """MERGER_INTEGRATION — org-wide cascade with integration-specific options."""

    async def test_merger_shock_options(self, client):
        target = await _target_dept(client)
        r = await client.post("/reality/shock", json={
            "shock_type": "MERGER_INTEGRATION", "target_id": target,
        })
        assert r.status_code == 200, f"{r.status_code}: {r.text[:300]}"
        body = r.json()

        assert body["impact"]["shock_type"] == "MERGER_INTEGRATION"
        assert "M&A" in body["impact"]["reasoning"] or "integration" in body["impact"]["reasoning"].lower()

        actions = [o["option"]["action"] for o in body["options_evaluated"]]
        assert "Phased Integration" in actions
        assert "Big-Bang Integration" in actions
        assert "Divest Overlapping Units" in actions

        # Big-bang must be costlier and riskier than phased
        by_action = {o["option"]["action"]: o for o in body["options_evaluated"]}
        phased = by_action["Phased Integration"]["score"]
        bigbang = by_action["Big-Bang Integration"]["score"]
        def cost(s):
            return int(s["estimated_cost"].replace("$", "").replace(",", ""))

        assert cost(bigbang) > cost(phased)
        assert bigbang["risk_penalty"] > phased["risk_penalty"]
        assert bigbang["estimated_time_days"] < phased["estimated_time_days"]

        assert body["recommendation"]["option"]["action"] in actions

    async def test_merger_severity_exceeds_baseline(self, client):
        """The same target hit by a merger cascades harder than a system outage."""
        target = await _target_dept(client)
        merger = (await client.post("/reality/shock", json={
            "shock_type": "MERGER_INTEGRATION", "target_id": target})).json()
        outage = (await client.post("/reality/shock", json={
            "shock_type": "SYSTEM_OUTAGE", "target_id": target})).json()
        assert merger["impact"]["severity"] >= outage["impact"]["severity"], \
            "M&A severity multiplier should dominate a plain outage on the same target"


@pytest.mark.asyncio
class TestCyberIncidentShock:
    """CYBER_INCIDENT — lateral-movement cascade with IR-specific options."""

    async def test_cyber_shock_options(self, client):
        target = await _target_dept(client)
        r = await client.post("/reality/shock", json={
            "shock_type": "CYBER_INCIDENT", "target_id": target,
        })
        assert r.status_code == 200, f"{r.status_code}: {r.text[:300]}"
        body = r.json()

        assert body["impact"]["shock_type"] == "CYBER_INCIDENT"
        actions = [o["option"]["action"] for o in body["options_evaluated"]]
        assert "Isolate & Restore" in actions
        assert "Full IR Engagement" in actions
        assert "Contain & Monitor" in actions

        by_action = {o["option"]["action"]: o for o in body["options_evaluated"]}
        # Full IR buys down risk at a cost premium; contain-only leaves the most risk
        assert by_action["Full IR Engagement"]["score"]["risk_penalty"] < \
               by_action["Contain & Monitor"]["score"]["risk_penalty"]

    async def test_shock_recorded_in_learning_history(self, client):
        """Cyber/merger shocks feed the learning loop like any other decision."""
        r = await client.get("/reality/learning")
        assert r.status_code == 200
        outcomes = r.json().get("historical_outcomes", [])
        types = {o.get("shock_type") for o in outcomes}
        assert {"MERGER_INTEGRATION", "CYBER_INCIDENT"} & types, \
            f"Expected merger/cyber shocks in learning history, got {types}"


@pytest.mark.asyncio
class TestPhysicsEngineScenarios:
    """Causal physics engine models both scenarios as feature interventions."""

    async def test_physics_merger_simulation(self, client):
        r = await client.post("/10x/physics/simulate", json={"shock_type": "MERGER_INTEGRATION"})
        assert r.status_code == 200, f"{r.status_code}: {r.text[:300]}"
        body = r.json()
        assert body["shock_type"] == "MERGER_INTEGRATION"
        assert body["nodes_affected"] > 0
        features = {e["feature"] for e in body["ripple_effect"]}
        assert "workforce_stability" in features
        assert "capability_redundancy" in features

    async def test_physics_cyber_simulation(self, client):
        r = await client.post("/10x/physics/simulate", json={"shock_type": "CYBER_INCIDENT"})
        assert r.status_code == 200, f"{r.status_code}: {r.text[:300]}"
        body = r.json()
        assert body["shock_type"] == "CYBER_INCIDENT"
        features = {e["feature"] for e in body["ripple_effect"]}
        assert "project_delivery" in features
        # A cyber incident must depress delivery — deltas for that feature are negative
        deltas = [e["delta"] for e in body["ripple_effect"] if e["feature"] == "project_delivery"]
        assert all(d < 0 for d in deltas), f"Cyber should hurt delivery, deltas: {deltas}"

    async def test_physics_unknown_shock_rejected(self, client):
        r = await client.post("/10x/physics/simulate", json={"shock_type": "ALIEN_INVASION"})
        assert r.status_code == 400

    async def test_physics_default_shock_still_works(self, client):
        """Backwards compatibility: empty body uses the default macro shock."""
        r = await client.post("/10x/physics/simulate")
        assert r.status_code == 200
        assert r.json()["shock_type"] == "MACRO_RATE_HIKE_50BPS"
