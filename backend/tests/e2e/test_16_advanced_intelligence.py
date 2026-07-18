"""
KAEOS E2E Test 16 — Advanced Intelligence Layers (10X)
Tests predictive ops (zero-prompt executions, pattern discovery), the
polymorphic engine, federated skill export, the quantum ledger / regulatory
engine, physics simulation, and the Pioneer external-intelligence layer.
"""
import pytest


@pytest.mark.asyncio
class TestPredictiveOps:
    """Predictive Operations — latent intent, ghost executions, patterns."""

    async def test_ghost_executions_list(self, client):
        """Zero-prompt (ghost) executions are retrievable."""
        r = await client.get("/predictive/ghost-executions")
        assert r.status_code == 200
        assert "ghost_executions" in r.json()

    async def test_analyze_signal_for_intent(self, client, has_ollama):
        """A seeded signal is analyzed for latent intent."""
        signals = (await client.get("/extraction/signals")).json().get("signals", [])
        if not signals:
            pytest.skip("No signals seeded")
        r = await client.post(f"/predictive/analyze-signal/{signals[0]['id']}")
        assert r.status_code == 200, f"{r.status_code}: {r.text[:300]}"
        assert r.json().get("status") in ("INTENT_DETECTED", "NO_LATENT_INTENT")

    async def test_analyze_unknown_signal_404(self, client):
        """Unknown signal id returns 404."""
        r = await client.post("/predictive/analyze-signal/not-a-signal-id")
        assert r.status_code == 404

    async def test_discover_patterns(self, client, has_ollama):
        """Pattern discovery engine runs over recent signals."""
        r = await client.post("/predictive/discover-patterns")
        assert r.status_code == 200, f"{r.status_code}: {r.text[:300]}"


@pytest.mark.asyncio
class TestPolymorphicEngine:
    """L25 Polymorphic — ambient UI generation and tool synthesis."""

    async def test_ambient_ui_generation(self, client, has_ollama):
        """Generates a persona-specific transient UI component (real LLM)."""
        if not has_ollama:
            pytest.skip("Ollama not running")
        r = await client.post("/polymorphic/ambient-ui", json={
            "persona": "CFO",
            "intent": "Review Q3 vendor payment anomalies",
            "data_context": {"anomalies": 3, "total_usd": 42000},
        })
        assert r.status_code == 200, f"{r.status_code}: {r.text[:300]}"

    async def test_polymorphic_events_ledger(self, client):
        """Polymorphic synthesis events are listed in the 10x ledger."""
        r = await client.get("/10x/polymorphic-events")
        assert r.status_code == 200

    async def test_synthesize_missing_integration(self, client, has_ollama):
        """The polymorphic engine auto-patches a skill's missing integration."""
        if not has_ollama:
            pytest.skip("Ollama not running")
        skills = (await client.get("/skills/")).json()["skills"]
        if not skills:
            pytest.skip("No skills to patch")
        # Unique name per run: colliding with a committed tool (e.g.
        # legacy_erp_bridge) is now REFUSED - generated code must never
        # overwrite source. Clean up the generated file afterwards.
        import os
        import uuid
        tool_name = f"e2e_synth_{uuid.uuid4().hex[:8]}"
        r = await client.post("/polymorphic/synthesize", json={
            "skill_id": skills[0]["skill_id"],
            "missing_integration": tool_name,
        })
        assert r.status_code == 200, f"{r.status_code}: {r.text[:300]}"
        generated = os.path.join(
            os.path.dirname(__file__), "..", "..", "app", "agents",
            "mcp_tools_dynamic", f"{tool_name}.py",
        )
        if os.path.exists(generated):
            os.remove(generated)


@pytest.mark.asyncio
class TestFederatedAndQuantum:
    """Federated exports + quantum provenance ledger."""

    async def test_federated_export_skill(self, client):
        """A skill can be exported as an anonymized federated pattern."""
        skills = (await client.get("/skills/")).json()["skills"]
        assert skills, "No skills seeded"
        r = await client.post(f"/federated/export-skill/{skills[0]['skill_id']}")
        assert r.status_code == 200, f"{r.status_code}: {r.text[:300]}"

    async def test_federated_exports_ledger(self, client):
        """Federated export history is listed."""
        r = await client.get("/10x/federated-exports")
        assert r.status_code == 200

    async def test_quantum_events(self, client):
        """Quantum ledger events endpoint is accessible."""
        r = await client.get("/10x/quantum-events")
        assert r.status_code == 200

    async def test_regulatory_rules(self, client):
        """Auto-generated regulatory rules endpoint is accessible."""
        r = await client.get("/10x/regulatory-rules")
        assert r.status_code == 200

    async def test_ingest_regulation(self, client, has_ollama):
        """Regulatory engine ingests a directive and generates compliance rules."""
        if not has_ollama:
            pytest.skip("Ollama not running")
        r = await client.post("/10x/ingest-regulation", json={
            "framework_name": "E2E Data Residency Act",
            "directive_text": "All customer PII must be stored in-region and "
                              "access-logged. Cross-border transfer requires DPO approval.",
            "urgency": "HIGH",
        })
        assert r.status_code == 200, f"{r.status_code}: {r.text[:300]}"

    async def test_precog_force_cycle(self, client, has_ollama):
        """Precognition engine force-runs a prediction cycle."""
        r = await client.post("/10x/precog/force-cycle")
        assert r.status_code == 200, f"{r.status_code}: {r.text[:300]}"

    async def test_physics_simulate(self, client):
        """Enterprise physics simulation runs."""
        r = await client.post("/10x/physics/simulate")
        assert r.status_code == 200, f"{r.status_code}: {r.text[:300]}"


@pytest.mark.asyncio
class TestPioneerExternalIntelligence:
    """P1 External Intelligence — signal ingest, correlation, alerts."""

    async def test_ingest_external_signal(self, client):
        """An external regulatory signal is ingested."""
        r = await client.post("/intelligence/signals", json={
            "signal_type": "REGULATORY",
            "source": "e2e_feed",
            "title": "New AI disclosure requirement",
            "content": "Regulator mandates disclosure of automated decision systems "
                       "used in employment decisions, effective next quarter.",
            "severity": "HIGH",
        })
        assert r.status_code == 200, f"{r.status_code}: {r.text[:300]}"

    async def test_invalid_signal_type_rejected(self, client):
        """Unknown signal_type is rejected with 400."""
        r = await client.post("/intelligence/signals", json={
            "signal_type": "NOT_A_TYPE", "source": "x", "title": "t", "content": "c",
        })
        assert r.status_code == 400

    async def test_correlate_signal_with_brain(self, client, has_ollama):
        """A signal correlates against the Company Brain."""
        r = await client.post("/intelligence/correlate", json={
            "signal_content": "Vendor payment thresholds changed by new SOX guidance",
        })
        assert r.status_code == 200, f"{r.status_code}: {r.text[:300]}"

    async def test_proactive_alert(self, client, has_ollama):
        """Proactive alert generation from an external signal."""
        r = await client.post("/intelligence/proactive-alert", json={
            "signal_type": "THREAT",
            "source": "e2e_feed",
            "title": "Credential stuffing wave",
            "content": "Industry-wide credential stuffing attacks targeting SSO portals.",
            "severity": "HIGH",
        })
        assert r.status_code == 200, f"{r.status_code}: {r.text[:300]}"

    async def test_redteam_scan_skill(self, client):
        """Red-team harness scans a specific skill on demand."""
        skills = (await client.get("/skills/")).json()["skills"]
        assert skills
        r = await client.post(f"/redteam/scan/{skills[0]['skill_id']}")
        assert r.status_code == 200, f"{r.status_code}: {r.text[:300]}"

    async def test_benchmark_intelligence_report(self, client):
        """Benchmark intelligence report aggregates network stats."""
        r = await client.get("/benchmark/intelligence-report")
        assert r.status_code == 200

    async def test_topology_knowledge_graph(self, client):
        """Alternate knowledge-graph endpoint returns nodes/edges."""
        r = await client.get("/topology/knowledge/graph")
        assert r.status_code == 200
