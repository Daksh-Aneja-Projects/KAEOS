"""
KAEOS E2E Test 10 — Infrastructure Layer
Tests model registry, cost governor, agent protocol, prompt templates,
LLM routing, and infrastructure dashboard.
"""
import pytest


@pytest.mark.asyncio
class TestInfrastructure:
    """Infrastructure Layer — model registry, cost governor, agent protocol."""

    # ── N1: Model Registry ──

    async def test_model_registry_list(self, client):
        """Model registry lists available models."""
        r = await client.get("/infrastructure/models")
        assert r.status_code == 200
        data = r.json()
        # /infrastructure/models returns a raw list directly
        models = data.get("models", data) if isinstance(data, dict) else data
        assert isinstance(models, list), f"Expected list, got {type(data)}"

    async def test_llm_providers(self, client):
        """LLM providers endpoint lists supported providers."""
        r = await client.get("/pipeline/llm/providers")
        assert r.status_code == 200

    async def test_prompt_templates(self, client):
        """Prompt templates are accessible."""
        r = await client.get("/infrastructure/prompts")
        assert r.status_code == 200

    # ── N2: Cost Governor ──

    async def test_cost_telemetry(self, client):
        """Cost telemetry returns usage data."""
        r = await client.get("/infrastructure/cost/telemetry?hours=24")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, dict)

    async def test_cost_budgets(self, client):
        """Cost budgets are accessible."""
        r = await client.get("/infrastructure/cost/budgets")
        assert r.status_code == 200

    # ── N3: Agent Protocol ──

    async def test_agent_registry(self, client):
        """Agent registry lists registered agents."""
        r = await client.get("/infrastructure/agents/registry")
        assert r.status_code == 200

    async def test_agent_messages(self, client):
        """Agent messages list."""
        r = await client.get("/infrastructure/agents/messages")
        assert r.status_code == 200

    # ── N4: Onboarding ──

    async def test_onboarding_sessions(self, client):
        """Onboarding sessions list."""
        r = await client.get("/infrastructure/onboarding")
        assert r.status_code == 200

    # ── Health Check ──

    async def test_backend_health(self, client):
        """Backend health check endpoint."""
        r = await client.get("http://localhost:8001/health")
        assert r.status_code == 200
        data = r.json()
        assert data.get("status") == "ok"

    # ── Infrastructure Dashboard via Brain ──

    async def test_knowledge_health_dashboard(self, client):
        """Knowledge health dashboard serves as infrastructure overview."""
        r = await client.get("/dashboard/health")
        assert r.status_code == 200
        data = r.json()
        assert "overall_score" in data or "score" in data or len(data) >= 2

    async def test_system_stats(self, client):
        """System stats from executive overview."""
        r = await client.get("/executive/overview")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, dict)

    async def test_schema_mappings(self, client):
        """Schema mappings endpoint."""
        r = await client.get("/infrastructure/schema-mappings")
        assert r.status_code == 200

    async def test_model_estimate(self, client):
        """Token budget estimation endpoint."""
        r = await client.get("/infrastructure/models/estimate?request_type=extraction")
        assert r.status_code == 200

    async def test_pipeline_connectors(self, client):
        """Pipeline available connectors."""
        r = await client.get("/pipeline/connectors/available")
        assert r.status_code == 200

    async def test_pipeline_transforms(self, client):
        """Pipeline available transforms."""
        r = await client.get("/pipeline/transforms/available")
        assert r.status_code == 200
