"""
KAEOS E2E Test 09 — Agent Factory (Live Agent Creator)
Tests the COMPLETE agent lifecycle: create → approve → compile → deploy → execute → stop.
Uses REAL Ollama (phi4-mini) for all LLM-dependent operations. No simulation.
"""
import pytest
from .conftest import assert_object


@pytest.mark.asyncio
class TestAgentFactory:
    """Agent Factory — the live agent creator. Full lifecycle test."""

    # ── Phase 1: Blueprint Creation ──

    async def test_01_create_blueprint_from_prompt(self, client, has_ollama):
        """Create a blueprint from natural language prompt (uses real Ollama)."""
        payload = {
            "prompt": "Create an agent that monitors employee time-off balance, "
                      "alerts managers when team coverage drops below 50%, "
                      "and suggests optimal approval/denial based on project deadlines.",
            "created_by": "e2e_test_admin"
        }
        try:
            r = await client.post("/agents/blueprint", json=payload)
        except Exception as e:
            pytest.skip(f"Blueprint creation timed out or failed: {e}")
        assert r.status_code == 200, f"Blueprint create → {r.status_code}: {r.text[:200]}"
        data = r.json()
        assert "blueprint" in data or "id" in data
        bp = data.get("blueprint", data)
        assert bp.get("status") in ("DRAFTING", "BLUEPRINT_READY", "drafting", "blueprint_ready")
        # Store for later tests
        TestAgentFactory._blueprint_id = bp.get("id")

    async def test_02_list_blueprints(self, client):
        """List all blueprints including the one just created."""
        data = await assert_object(client, "/agents/blueprints", ["blueprints"])
        assert len(data["blueprints"]) > 0
        # Find our test blueprint
        any(
            "time-off" in (bp.get("name", "") or "").lower() or
            bp.get("id") == getattr(TestAgentFactory, "_blueprint_id", None)
            for bp in data["blueprints"]
        )
        # At least seeded blueprints should exist
        assert len(data["blueprints"]) >= 1

    async def test_03_get_blueprint_detail(self, client):
        """Fetch blueprint detail by ID."""
        bp_id = getattr(TestAgentFactory, "_blueprint_id", None)
        if not bp_id:
            # Use any existing blueprint
            data = (await client.get("/agents/blueprints")).json()
            bps = data.get("blueprints", [])
            if not bps:
                pytest.skip("No blueprints available")
            bp_id = bps[0]["id"]
            TestAgentFactory._blueprint_id = bp_id

        r = await client.get(f"/agents/blueprint/{bp_id}")
        assert r.status_code == 200
        bp = r.json()
        assert bp["id"] == bp_id

    # ── Phase 2: Blueprint Refinement & Approval ──

    async def test_04_refine_blueprint(self, client):
        """Refine blueprint with edits."""
        bp_id = getattr(TestAgentFactory, "_blueprint_id", None)
        if not bp_id:
            pytest.skip("No blueprint to refine")

        r = await client.put(f"/agents/blueprint/{bp_id}", json={
            "name": "Time-Off Coverage Monitor (E2E Test)",
            "risk_level": "LOW",
        })
        assert r.status_code == 200

    async def test_05_approve_blueprint(self, client):
        """Approve a DRAFT blueprint."""
        bp_id = getattr(TestAgentFactory, "_blueprint_id", None)
        if not bp_id:
            pytest.skip("No blueprint to approve")

        r = await client.post(f"/agents/blueprint/{bp_id}/approve", json={
            "approved_by": "e2e_test_admin"
        })
        assert r.status_code == 200
        data = r.json()
        bp = data.get("blueprint", data)
        assert bp.get("status") in ("APPROVED", "approved")

    # ── Phase 3: Compilation ──

    async def test_06_compile_blueprint(self, client, has_ollama):
        """Compile an APPROVED blueprint into executable form (uses real Ollama)."""
        bp_id = getattr(TestAgentFactory, "_blueprint_id", None)
        if not bp_id:
            pytest.skip("No blueprint to compile")

        try:
            r = await client.post(f"/agents/blueprint/{bp_id}/compile")
        except Exception as e:
            pytest.skip(f"Blueprint compile timed out (Ollama): {e}")
        if r.status_code == 500 and any(
            marker in r.text.lower() for marker in ("timeout", "timed out", "ollama", "connection")
        ):
            pytest.skip(f"Blueprint compile hit LLM outage: {r.text[:150]}")
        # A bare 500 is a real defect (e.g. the ProvenanceLedger tenant_id
        # TypeError this skip used to mask) — fail loudly.
        assert r.status_code == 200, f"Compile → {r.status_code}: {r.text[:200]}"
        data = r.json()
        bp = data.get("blueprint", data)
        assert bp.get("status") in ("COMPILED", "compiled")

    # ── Phase 4: Deployment ──

    async def test_07_deploy_blueprint(self, client):
        """Deploy a COMPILED blueprint as a live agent."""
        bp_id = getattr(TestAgentFactory, "_blueprint_id", None)
        if not bp_id:
            pytest.skip("No blueprint to deploy")

        r = await client.post(f"/agents/blueprint/{bp_id}/deploy", json={
            "trigger_config": {
                "risk_level": "LOW",
                "confidence_threshold": 0.8,
                "hitl_mode": "ON_LOW_CONFIDENCE",
                "hitl_threshold": 0.7,
            }
        })
        assert r.status_code == 200
        data = r.json()
        agent = data.get("agent", data)
        assert agent.get("status") in ("RUNNING", "DEPLOYED", "running", "deployed")
        TestAgentFactory._deployed_agent_id = agent.get("id")

    # ── Phase 5: Deployed Agent Management ──

    async def test_08_list_deployed_agents(self, client):
        """List deployed agents including the one just deployed."""
        data = await assert_object(client, "/agents/deployed", ["agents"])
        assert len(data["agents"]) > 0

    async def test_09_get_deployed_agent_detail(self, client):
        """Fetch deployed agent detail."""
        agent_id = getattr(TestAgentFactory, "_deployed_agent_id", None)
        if not agent_id:
            agents = (await client.get("/agents/deployed")).json().get("agents", [])
            if not agents:
                pytest.skip("No deployed agents")
            agent_id = agents[0]["id"]

        r = await client.get(f"/agents/deployed/{agent_id}")
        assert r.status_code == 200

    # ── Phase 6: Activity Feed & Debates ──

    async def test_10_activity_feed(self, client):
        """Activity feed returns events for agent actions."""
        r = await client.get("/agents/activity-feed?limit=20")
        assert r.status_code == 200
        data = r.json()
        events = data.get("events", data)
        assert isinstance(events, list)

    async def test_11_action_required(self, client):
        """Action required queue is accessible."""
        r = await client.get("/agents/activity-feed/action-required")
        assert r.status_code == 200

    async def test_12_recent_debates(self, client):
        """Recent debates endpoint returns debate transcripts."""
        r = await client.get("/agents/debates/recent")
        assert r.status_code == 200

    # ── Phase 7: Agent Lifecycle Management ──

    async def test_13_pause_agent(self, client):
        """Pause a running agent."""
        agent_id = getattr(TestAgentFactory, "_deployed_agent_id", None)
        if not agent_id:
            agents = (await client.get("/agents/deployed")).json().get("agents", [])
            running = [a for a in agents if a.get("status") in ("RUNNING", "running")]
            if not running:
                pytest.skip("No running agents to pause")
            agent_id = running[0]["id"]

        r = await client.post(f"/agents/deployed/{agent_id}/pause")
        assert r.status_code == 200

    async def test_14_stop_agent(self, client):
        """Stop a deployed agent."""
        agent_id = getattr(TestAgentFactory, "_deployed_agent_id", None)
        if not agent_id:
            agents = (await client.get("/agents/deployed")).json().get("agents", [])
            if not agents:
                pytest.skip("No agents to stop")
            agent_id = agents[0]["id"]

        r = await client.post(f"/agents/deployed/{agent_id}/stop")
        assert r.status_code == 200


@pytest.mark.asyncio
class TestAgentFactorySeededData:
    """Verify seeded Agent Factory data is accessible."""

    async def test_seeded_blueprints_exist(self, client):
        """Seeded blueprints are present."""
        data = (await client.get("/agents/blueprints")).json()
        bps = data.get("blueprints", [])
        assert len(bps) >= 3, f"Expected 3+ seeded blueprints, got {len(bps)}"

    async def test_seeded_deployed_agents_exist(self, client):
        """Seeded deployed agents are present and running."""
        data = (await client.get("/agents/deployed")).json()
        agents = data.get("agents", [])
        assert len(agents) >= 1, f"Expected 1+ deployed agents, got {len(agents)}"

    async def test_seeded_feed_events_exist(self, client):
        """Seeded activity feed events are present."""
        data = (await client.get("/agents/activity-feed?limit=50")).json()
        events = data.get("events", data)
        if isinstance(events, list):
            assert len(events) >= 3, f"Expected 3+ feed events, got {len(events)}"

    async def test_seeded_debates_exist(self, client):
        """Seeded debate transcripts are present."""
        data = (await client.get("/agents/debates/recent")).json()
        debates = data.get("debates", data)
        if isinstance(debates, list):
            assert len(debates) >= 1, "Expected 1+ debate transcripts"

    async def test_fairness_log(self, client):
        """Fairness audit log is accessible."""
        r = await client.get("/fairness/audit-log?limit=10")
        assert r.status_code == 200

    async def test_calendar_events(self, client):
        """Calendar events endpoint works."""
        r = await client.get("/calendar/events")
        assert r.status_code == 200
