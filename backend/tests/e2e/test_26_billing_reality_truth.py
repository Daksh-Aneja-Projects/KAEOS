"""
KAEOS E2E Test 26 — Billing & Reality: derived, not fabricated

Two stub surfaces were replaced with real computation. These tests exist to stop
the fabrications coming back:

  * /billing/* multiplied an execution count by a hardcoded $0.015 and asserted
    "0.5 hours saved per execution". Both were invented. Usage is now metered
    from CostEvent rows and hours_saved is null (it needs a tenant baseline).
  * /reality/* kept its provenance feed and shock history in module-level Python
    lists — wiped on restart and shared across tenants, despite the platform
    selling an immutable, tenant-scoped audit trail. Both are tables now.
"""
import pytest


@pytest.mark.asyncio
class TestBillingIsMetered:
    """Usage must reconcile with recorded cost events, not a constant."""

    async def test_usage_reports_real_token_metering(self, client):
        r = await client.get("/billing/usage")
        assert r.status_code == 200
        data = r.json()
        for key in ("metered_calls", "input_tokens", "output_tokens",
                    "total_cost_usd", "by_tier", "by_model", "metering_active"):
            assert key in data, f"Missing '{key}'. Keys: {list(data)}"
        assert data["total_tokens"] == data["input_tokens"] + data["output_tokens"]

    async def test_usage_cost_is_not_the_old_hardcoded_formula(self, client):
        """Regression: cost must not simply be executions x $0.015."""
        data = (await client.get("/billing/usage")).json()
        if not data["metering_active"]:
            pytest.skip("No cost events recorded yet")
        fabricated = round((data["total_executions"] or 0) * 0.015, 2)
        # Only meaningful when the fabricated number would be non-zero.
        if fabricated > 0:
            assert round(data["total_cost_usd"], 2) != fabricated, (
                "billing/usage still returns the hardcoded $0.015/execution figure"
            )

    async def test_tier_attribution_reconciles_with_total(self, client):
        data = (await client.get("/billing/usage")).json()
        if not data["by_tier"]:
            pytest.skip("No metered calls to attribute")
        assert sum(t["calls"] for t in data["by_tier"].values()) == data["metered_calls"]

    async def test_roi_reports_safe_autonomy_not_invented_savings(self, client):
        r = await client.get("/billing/roi")
        assert r.status_code == 200
        data = r.json()

        # The honest position: savings need a tenant-supplied human baseline.
        assert data["total_hours_saved"] is None, (
            "hours_saved must stay null until a human baseline is configured"
        )
        assert data["total_cost_reduction"] is None
        assert data.get("note")

        # What IS measurable must be present.
        assert "safe_autonomy_rate_pct" in data
        if data["total_executions"]:
            assert 0 <= data["safe_autonomy_rate_pct"] <= 100
            assert data["autonomous_executions"] <= data["total_executions"]

    async def test_roi_autonomy_rate_reconciles_with_executions(self, client):
        data = (await client.get("/billing/roi")).json()
        if not data["total_executions"]:
            pytest.skip("No executions recorded")
        expected = round(data["autonomous_executions"] / data["total_executions"] * 100, 1)
        assert data["safe_autonomy_rate_pct"] == expected


@pytest.mark.asyncio
class TestRealityIsPersisted:
    """The feed and shock history must be DB-backed and tenant-scoped."""

    async def test_provenance_feed_shape(self, client):
        r = await client.get("/reality/provenance")
        assert r.status_code == 200
        feed = r.json()["feed"]
        assert isinstance(feed, list)
        if feed:
            for key in ("id", "event", "ts"):
                assert key in feed[0], f"Missing '{key}'. Keys: {list(feed[0])}"

    async def test_shock_writes_durable_feed_and_outcome(self, client):
        twin = (await client.get("/reality/twin")).json()
        if not twin.get("nodes"):
            pytest.skip("Twin has no nodes")
        target = twin["nodes"][0]["id"]

        before_feed = len((await client.get("/reality/provenance")).json()["feed"])
        before_shocks = (await client.get("/reality/learning")).json()["shocks_processed"]

        r = await client.post("/reality/shock", json={
            "shock_type": "VENDOR_FAILURE", "target_id": target,
        })
        assert r.status_code == 200, f"shock failed: {r.text[:200]}"

        after_feed = (await client.get("/reality/provenance")).json()["feed"]
        assert len(after_feed) > before_feed or len(after_feed) == 50, \
            "Shock must append to the persisted provenance feed"

        learning = (await client.get("/reality/learning")).json()
        assert learning["shocks_processed"] > before_shocks, \
            "Shock outcome must be persisted for the learning loop"

    async def test_learning_modifiers_are_derived_from_outcomes(self, client):
        """
        Regression: modifiers were hardcoded to {"MITIGATE_FAILURE": 5.0,
        "REDUCE_DEPENDENCY": 2.5} regardless of what actually happened.
        """
        data = (await client.get("/reality/learning")).json()
        if not data["shocks_processed"]:
            pytest.skip("No shock outcomes recorded")

        modifiers = data["modifiers"]
        assert modifiers, "Recorded outcomes must produce learned modifiers"
        assert modifiers != {"MITIGATE_FAILURE": 5.0, "REDUCE_DEPENDENCY": 2.5}, \
            "learning modifiers are still the hardcoded pair"

        # Every modifier must correspond to a decision actually taken.
        decisions = {o["decision"] for o in data["historical_outcomes"] if o.get("decision")}
        if decisions:
            assert set(modifiers) & decisions, \
                "Modifiers must key off decisions that were actually recorded"

    async def test_decisions_endpoint_returns_persisted_rows(self, client):
        r = await client.get("/reality/decision")
        assert r.status_code == 200
        decisions = r.json()["decisions"]
        assert isinstance(decisions, list)
        if decisions:
            for key in ("shock_type", "decision", "severity", "ts"):
                assert key in decisions[0]

    async def test_historical_outcomes_carry_real_severity(self, client):
        data = (await client.get("/reality/learning")).json()
        outcomes = data["historical_outcomes"]
        if not outcomes:
            pytest.skip("No outcomes recorded")
        for o in outcomes:
            if o.get("severity") is not None:
                assert 0 <= o["severity"] <= 100, f"severity out of range: {o['severity']}"
