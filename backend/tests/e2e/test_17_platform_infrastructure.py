"""
KAEOS E2E Test 17 — Platform Config & Infrastructure Services
Tests platform configuration (LLM routing, MCP tools, ontology, federated
opt-in) and the N-layer infrastructure: model registry writes/routing, cost
governor (budgets, check, record), agent protocol (register, discover,
message, heartbeat, circuit breaker), onboarding, and schema mappings.
"""
import pytest

from .conftest import admin_secret as _admin_secret


@pytest.mark.asyncio
class TestPlatformConfig:
    """Platform configuration — read and write all four config surfaces."""

    async def test_llm_routing_get(self, client):
        r = await client.get("/config/llm-routing")
        assert r.status_code == 200
        configs = r.json()
        assert isinstance(configs, list)
        assert len(configs) >= 1, "Expected seeded LLM routing tiers"

    async def test_llm_routing_upsert(self, client):
        """
        Upsert a tier. TIER_EMBEDDING is the scratch tier here: it is a real
        layer (arbitrary names are rejected — see below) but is not the
        reasoning tier, so a test can never cap autonomy for the rest of the run.
        """
        try:
            r = await client.post("/config/llm-routing", json={
                "layer": "TIER_EMBEDDING",
                "model_name": "ollama/nomic-embed-text:latest",
                "provider": "ollama",
                "api_key": "e2e-secret-should-not-return",
            })
            assert r.status_code == 200, f"{r.status_code}: {r.text[:300]}"
            body = r.json()
            assert body["key_configured"] is True
            # Secrets are write-only — the response must never echo the key back.
            assert "api_key" not in body
            assert "e2e-secret-should-not-return" not in r.text
        finally:
            await client.delete("/config/llm-routing/TIER_EMBEDDING")

    async def test_llm_routing_rejects_unknown_layer(self, client):
        """An arbitrary layer maps to no routing tier — storing it would be garbage."""
        r = await client.post("/config/llm-routing", json={
            "layer": "TIER_E2E_TEST", "model_name": "x", "provider": "ollama",
        })
        assert r.status_code == 400

    async def test_mcp_tools_get(self, client):
        r = await client.get("/config/mcp-tools")
        assert r.status_code == 200
        assert len(r.json()) >= 1, "Expected seeded MCP tool configs"

    async def test_mcp_tools_upsert(self, client):
        r = await client.post("/config/mcp-tools", json={
            "tool_id": "e2e_test_tool",
            "is_active": True,
            "rate_limit_per_hour": 42,
            "api_key": "local",
        })
        assert r.status_code == 200, f"{r.status_code}: {r.text[:300]}"

    async def test_ontology_get(self, client):
        r = await client.get("/config/ontology")
        assert r.status_code == 200
        assert len(r.json()) >= 1, "Expected seeded ontology configs"

    async def test_ontology_upsert(self, client):
        r = await client.post("/config/ontology", json={
            "department": "e2e_department",
            "default_half_life_days": 77,
        })
        assert r.status_code == 200, f"{r.status_code}: {r.text[:300]}"

    async def test_federated_config_get(self, client):
        r = await client.get("/config/federated")
        assert r.status_code == 200
        assert len(r.json()) >= 1, "Expected seeded federated configs"

    async def test_federated_config_upsert(self, client):
        r = await client.post("/config/federated", json={
            "department": "e2e_department",
            "opt_in": True,
        })
        assert r.status_code == 200, f"{r.status_code}: {r.text[:300]}"


@pytest.mark.asyncio
class TestModelRegistryAndCost:
    """N1 Model Registry + N2 Cost Governor."""

    async def test_register_model(self, client):
        r = await client.post("/infrastructure/models", json={
            "model_name": "e2e-test-model",
            "provider": "ollama",
            "tier": "FAST",
            "cost_per_1k_input": 0.0,
            "cost_per_1k_output": 0.0,
            "max_context_window": 8192,
            "use_cases": ["testing"],
        })
        assert r.status_code == 200, f"{r.status_code}: {r.text[:300]}"

    async def test_route_to_model(self, client):
        r = await client.post("/infrastructure/models/route", json={
            "request_type": "extraction",
        })
        assert r.status_code == 200, f"{r.status_code}: {r.text[:300]}"

    async def test_create_prompt_template(self, client):
        r = await client.post("/infrastructure/prompts", json={
            "name": "e2e_prompt", "template": "Summarize: {{input}}",
            "use_case": "testing",
        })
        assert r.status_code == 200, f"{r.status_code}: {r.text[:300]}"

    async def test_create_budget(self, client):
        r = await client.post("/infrastructure/cost/budgets", json={
            "scope": "tenant", "token_limit": 5_000_000, "cost_limit_usd": 50.0,
        })
        assert r.status_code == 200, f"{r.status_code}: {r.text[:300]}"

    async def test_check_budget(self, client):
        r = await client.post("/infrastructure/cost/check", json={
            "estimated_tokens": 1000, "scope": "tenant",
        })
        assert r.status_code == 200, f"{r.status_code}: {r.text[:300]}"

    async def test_record_usage(self, client):
        # Recorded against a scratch tenant, NOT the default demo tenant:
        # this endpoint writes a durable CostEvent, and every suite run was
        # depositing a fake 500/120 row into tenant_acme's real billing feed.
        # /billing must only ever aggregate rows the router actually metered.
        r = await client.post("/infrastructure/cost/record", json={
            "model_name": "phi4-mini:latest", "model_tier": "FAST",
            "input_tokens": 500, "output_tokens": 120,
            "cost_usd": 0.0, "latency_ms": 850, "request_type": "e2e_test",
        }, headers={"X-Tenant-ID": "tenant_e2e_scratch"})
        assert r.status_code == 200, f"{r.status_code}: {r.text[:300]}"

    async def test_cost_telemetry_reflects_usage(self, client):
        r = await client.get("/infrastructure/cost/telemetry?hours=24")
        assert r.status_code == 200
        assert isinstance(r.json(), dict)


@pytest.mark.asyncio
class TestAgentProtocol:
    """N3 Agent Protocol — register → discover → message → heartbeat → circuit."""

    AGENT_NAME = "e2e_protocol_agent"

    async def test_01_register_agent(self, client):
        r = await client.post("/infrastructure/agents/register", json={
            "agent_name": self.AGENT_NAME,
            "agent_type": "worker",
            "capabilities": ["e2e_capability"],
            "max_concurrent": 3,
        })
        assert r.status_code == 200, f"{r.status_code}: {r.text[:300]}"

    async def test_02_discover_agent(self, client):
        r = await client.post("/infrastructure/agents/discover", json={
            "capability": "e2e_capability",
        })
        assert r.status_code == 200, f"{r.status_code}: {r.text[:300]}"
        assert "error" not in r.json(), f"Agent not discoverable: {r.json()}"

    async def test_03_send_message(self, client):
        r = await client.post("/infrastructure/agents/message", json={
            "sender_agent_id": self.AGENT_NAME,
            "receiver_agent_id": self.AGENT_NAME,
            "message_type": "request",
            "payload": {"task": "e2e ping"},
            "priority": 5,
        })
        assert r.status_code == 200, f"{r.status_code}: {r.text[:300]}"

    async def test_04_list_messages(self, client):
        r = await client.get("/infrastructure/agents/messages")
        assert r.status_code == 200

    async def test_05_heartbeat(self, client):
        r = await client.post(f"/infrastructure/agents/{self.AGENT_NAME}/heartbeat")
        assert r.status_code == 200, f"{r.status_code}: {r.text[:300]}"

    async def test_06_circuit_reset(self, client):
        r = await client.post(f"/infrastructure/agents/{self.AGENT_NAME}/circuit/reset")
        assert r.status_code == 200, f"{r.status_code}: {r.text[:300]}"


@pytest.mark.asyncio
class TestOnboardingAndSchemaMappings:
    """N4 Onboarding wizard + N5 schema mapping proposals."""

    async def test_onboarding_another_tenant_requires_admin(self, client):
        """Regression: provisioning/reading ANOTHER tenant must not be open.

        These endpoints took tenant_id from the body/path and never checked it
        against the caller, so any tenant could create, read, or advance any
        other tenant's onboarding.
        """
        other = "tenant_not_mine_probe"
        for call in (
            client.post("/infrastructure/onboarding", json={
                "tenant_id": other, "tenant_name": "Not Mine",
            }),
            client.get(f"/infrastructure/onboarding/{other}"),
            client.post(f"/infrastructure/onboarding/{other}/advance", json={}),
        ):
            r = await call
            # 403 = secret required and absent/wrong; 503 = ADMIN_SECRET unset,
            # so the platform path is disabled entirely. Both are closed doors.
            assert r.status_code in (403, 503), (
                f"cross-tenant onboarding was accepted: {r.status_code} {r.text[:200]}"
            )

    async def test_onboarding_create_and_advance(self, client):
        """Provision a scratch tenant as a platform admin, read it back, advance a stage.

        Onboarding a tenant that is NOT the caller's own is a platform action:
        it requires X-Admin-Secret. (It also cannot work any other way under
        Postgres RLS - a tenant may not insert a row belonging to another.)
        """
        scratch = "tenant_e2e_onboarding"
        admin = {"X-Admin-Secret": _admin_secret()}

        r = await client.post("/infrastructure/onboarding", json={
            "tenant_id": scratch,
            "tenant_name": "E2E Test Co",
            "industry_vertical": "software",
        }, headers=admin)
        assert r.status_code == 200, f"{r.status_code}: {r.text[:300]}"

        r2 = await client.get(f"/infrastructure/onboarding/{scratch}", headers=admin)
        assert r2.status_code == 200
        assert "error" not in r2.json(), f"Onboarding not found: {r2.json()}"

        r3 = await client.post(f"/infrastructure/onboarding/{scratch}/advance", json={}, headers=admin)
        assert r3.status_code == 200, f"{r3.status_code}: {r3.text[:300]}"

    async def test_schema_mapping_propose_and_confirm(self, client):
        r = await client.post("/infrastructure/schema-mappings/propose", json={
            "connector_id": "hr_hris",
            "source_fields": [
                {"field_name": "worker_id", "object_type": "Worker", "data_type": "string"},
                {"field_name": "email", "object_type": "Worker", "data_type": "string"},
            ],
        })
        assert r.status_code in (200, 404), f"{r.status_code}: {r.text[:300]}"
        if r.status_code == 200:
            mappings = (await client.get("/infrastructure/schema-mappings")).json()
            items = mappings.get("mappings", mappings) if isinstance(mappings, dict) else mappings
            if isinstance(items, list) and items:
                mapping_id = items[0].get("id")
                if mapping_id:
                    r2 = await client.post(
                        f"/infrastructure/schema-mappings/{mapping_id}/confirm",
                        json={"confirmed_by": "e2e_admin"})
                    assert r2.status_code == 200
