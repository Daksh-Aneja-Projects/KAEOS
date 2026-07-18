"""
KAEOS E2E Test 24 — BYOK Adaptive Model Layer

Covers the promise that the platform adapts to whatever model a tenant brings:
- Model routing config is tenant-scoped and secrets are never serialized back
  (regression test for the old LLMRoutingConfig, which had `layer` globally
  unique and returned plaintext api_key from a non-tenant-scoped GET).
- The capability probe calibrates a real model and persists a profile.
- The probe's tier_ceiling caps autonomy: a weak model on the reasoning tier
  forces otherwise-autonomous skills to human review.
- Changing the model invalidates the stale capability profile.
"""
import pytest

from .conftest import skip_if_llm_outage

SECRET = "sk-e2e-must-never-be-returned"


@pytest.mark.asyncio
class TestByokConfigSecurity:
    """Tenant scoping + secret hygiene on /config/llm-routing."""

    async def test_list_never_exposes_api_key(self, client):
        r = await client.get("/config/llm-routing")
        assert r.status_code == 200
        rows = r.json()
        assert isinstance(rows, list)
        for row in rows:
            assert "api_key" not in row, f"api_key must never be serialized: {row}"
            assert "api_key_encrypted" not in row
            assert "key_configured" in row

    async def test_store_key_then_never_read_it_back(self, client):
        r = await client.post("/config/llm-routing", json={
            "layer": "TIER_3_FAST",
            "model_name": "ollama/phi4-mini:latest",
            "provider": "ollama",
            "api_key": SECRET,
        })
        assert r.status_code == 200, f"upsert failed: {r.text[:200]}"
        created = r.json()
        assert created["key_configured"] is True
        assert SECRET not in r.text

        # The secret must not surface anywhere in the list response.
        listing = await client.get("/config/llm-routing")
        assert SECRET not in listing.text, "Stored API key leaked through GET"

    async def test_invalid_layer_rejected(self, client):
        r = await client.post("/config/llm-routing", json={
            "layer": "NOT_A_TIER", "model_name": "x", "provider": "ollama",
        })
        assert r.status_code == 400

    async def test_upsert_is_idempotent_per_layer(self, client):
        payload = {
            "layer": "TIER_3_FAST",
            "model_name": "ollama/phi4-mini:latest",
            "provider": "ollama",
        }
        first = (await client.post("/config/llm-routing", json=payload)).json()
        second = (await client.post("/config/llm-routing", json=payload)).json()
        assert first["id"] == second["id"], "Upsert must update in place, not duplicate the layer"

    async def test_delete_unknown_layer_404(self, client):
        r = await client.delete("/config/llm-routing/TIER_EMBEDDING")
        assert r.status_code in (200, 404)  # 200 if a previous run configured it


@pytest.mark.asyncio
@pytest.mark.ollama
class TestCapabilityProbe:
    """The probe must calibrate a real model and persist the profile."""

    async def test_probe_unknown_layer_404(self, client):
        r = await client.post("/config/llm-routing/TIER_DOES_NOT_EXIST/probe")
        assert r.status_code == 404

    async def test_probe_returns_capability_profile(self, client, has_ollama):
        if not has_ollama:
            pytest.skip("Probe needs a reachable model provider")

        await client.post("/config/llm-routing", json={
            "layer": "TIER_2_STANDARD",
            "model_name": "ollama/phi4-mini:latest",
            "provider": "ollama",
        })
        r = await client.post("/config/llm-routing/TIER_2_STANDARD/probe")
        skip_if_llm_outage(r)
        assert r.status_code == 200, f"probe failed: {r.text[:300]}"

        profile = r.json()["profile"]
        for key in ("json_compliance", "reasoning_depth", "instruction_following",
                    "tier_ceiling", "latency_ms", "probed_at", "usable", "recommendation"):
            assert key in profile, f"Missing '{key}' in profile. Keys: {list(profile)}"
        assert 0.0 <= profile["tier_ceiling"] <= 1.0
        assert profile["usable"] is True, f"Live model probed as unusable: {profile.get('errors')}"

    async def test_profile_persists_on_config(self, client, has_ollama):
        if not has_ollama:
            pytest.skip("Probe needs a reachable model provider")
        rows = (await client.get("/config/llm-routing")).json()
        standard = next((r for r in rows if r["layer"] == "TIER_2_STANDARD"), None)
        if not standard or not standard.get("capability_profile"):
            pytest.skip("TIER_2_STANDARD not probed in this run")
        assert "tier_ceiling" in standard["capability_profile"]

    async def test_changing_model_invalidates_profile(self, client, has_ollama):
        if not has_ollama:
            pytest.skip("Probe needs a reachable model provider")

        await client.post("/config/llm-routing", json={
            "layer": "TIER_2_STANDARD", "model_name": "ollama/phi4-mini:latest", "provider": "ollama",
        })
        probe = await client.post("/config/llm-routing/TIER_2_STANDARD/probe")
        skip_if_llm_outage(probe)
        assert probe.json()["profile"]["tier_ceiling"] is not None

        # Switching model must clear the now-meaningless profile.
        switched = await client.post("/config/llm-routing", json={
            "layer": "TIER_2_STANDARD", "model_name": "ollama/llama3.2:1b", "provider": "ollama",
        })
        assert switched.json()["capability_profile"] == {}, \
            "A model change must invalidate the previous capability profile"

        # Restore the working default for subsequent tests.
        await client.post("/config/llm-routing", json={
            "layer": "TIER_2_STANDARD", "model_name": "ollama/phi4-mini:latest", "provider": "ollama",
        })


@pytest.mark.asyncio
class TestCeilingDrivesGovernance:
    """
    The load-bearing behavior: a weak model earns a low ceiling, which caps
    effective confidence and pushes autonomous decisions to human review.
    """

    async def test_weak_model_forces_hitl_then_restores(self, client, has_ollama):
        if not has_ollama:
            pytest.skip("Needs a reachable model provider")

        skills = (await client.get("/skills/?min_confidence=0.85")).json().get("skills", [])
        if not skills:
            pytest.skip("No high-confidence skill available")
        skill_id = skills[0]["skill_id"]

        # Baseline: reasoning tier unprobed → no cap → autonomous.
        await client.post("/config/llm-routing", json={
            "layer": "TIER_1_COMPLEX", "model_name": "ollama/qwen2.5-coder:7b", "provider": "ollama",
        })
        base = await client.post(f"/skills/{skill_id}/execute", json={"intent": "byok baseline"})
        skip_if_llm_outage(base)
        assert base.status_code == 200
        assert base.json()["hitl_required"] is False, "Unprobed tier must not cap autonomy"

        try:
            # Probe a weak model onto the reasoning tier.
            await client.post("/config/llm-routing", json={
                "layer": "TIER_1_COMPLEX", "model_name": "ollama/phi4-mini:latest", "provider": "ollama",
            })
            probe = await client.post("/config/llm-routing/TIER_1_COMPLEX/probe")
            skip_if_llm_outage(probe)
            ceiling = probe.json()["profile"]["tier_ceiling"]
            if ceiling >= 0.82:
                pytest.skip(f"Probe model scored {ceiling} — too capable to demonstrate capping")

            gated = await client.post(f"/skills/{skill_id}/execute", json={"intent": "byok ceiling"})
            skip_if_llm_outage(gated)
            assert gated.status_code == 200
            assert gated.json()["hitl_required"] is True, (
                f"Model ceiling {ceiling} < 0.82 must force HITL on the same skill"
            )
        finally:
            # Always restore the capable default, or the rest of the suite gates.
            await client.post("/config/llm-routing", json={
                "layer": "TIER_1_COMPLEX", "model_name": "ollama/qwen2.5-coder:7b", "provider": "ollama",
            })

        restored = await client.post(f"/skills/{skill_id}/execute", json={"intent": "byok restore"})
        skip_if_llm_outage(restored)
        assert restored.json()["hitl_required"] is False, "Autonomy must return once the cap is removed"
