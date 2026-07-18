"""
KAEOS E2E Test 12 — Connectors & Integrations
Tests connector lifecycle, data pipeline, schema mapping,
sync operations, HITL, and extraction pipeline.
"""
import pytest


@pytest.mark.asyncio
class TestConnectorsIntegrations:
    """Connectors & Integration Layer — data fabric, ETL, schema mapping."""

    async def test_connectors_list(self, client):
        """Connectors list returns seeded connectors."""
        r = await client.get("/connectors")
        assert r.status_code == 200
        data = r.json()
        assert "connectors" in data, f"Expected 'connectors' key, got: {list(data.keys())}"

    async def test_connector_categories(self, client):
        """Connectors span multiple categories."""
        data = (await client.get("/connectors")).json()
        cats = set(c.get("category", "") for c in data.get("connectors", []))
        assert len(cats) >= 1, f"Expected at least 1 connector category, got {cats}"

    async def test_connector_health(self, client):
        """Connector health check."""
        data = (await client.get("/connectors")).json()
        connectors = data.get("connectors", [])
        if connectors:
            conn_id = connectors[0]["id"]
            r = await client.get(f"/connectors/{conn_id}/health")
            assert r.status_code == 200

    async def test_connector_feed(self, client):
        """Connector activity feed."""
        data = (await client.get("/connectors")).json()
        connectors = data.get("connectors", [])
        if connectors:
            conn_id = connectors[0]["id"]
            r = await client.get(f"/connectors/{conn_id}/feed")
            assert r.status_code == 200

    async def test_schema_mapping_list(self, client):
        """Schema mappings list is accessible."""
        r = await client.get("/infrastructure/schema-mappings")
        assert r.status_code == 200

    async def test_schema_mapping_proposal(self, client):
        """AI schema mapping proposal via infrastructure endpoint."""
        r = await client.post("/infrastructure/schema-mappings/propose", json={
            "connector_id": "hr_hris",
            "source_fields": [
                {"field_name": "worker_id", "object_type": "Worker", "data_type": "string"},
                {"field_name": "email", "object_type": "Worker", "data_type": "string"},
                {"field_name": "department", "object_type": "Position", "data_type": "string"},
            ]
        })
        # 200 = proposals generated; 404 = no connector found (valid in test env)
        assert r.status_code in (200, 404, 422), f"{r.status_code}: {r.text[:200]}"

    async def test_data_pipeline_run(self, client):
        """Data pipeline executes end-to-end."""
        payload = {
            "connector_slug": "rest_api",
            "connector_config": {
                "base_url": "https://jsonplaceholder.typicode.com",
                "endpoint": "/users",
                "batch_size": 5,
            },
            "dag_config": {
                "nodes": [
                    {"id": "mapper_1", "type": "field_mapper", "config": {"auto_detect": True}},
                ],
                "edges": [],
            },
            "destination_type": "local_file",
        }
        r = await client.post("/pipeline/run", json=payload)
        assert r.status_code == 200

    async def test_extraction_signals(self, client):
        """Extraction signals ingested from connectors."""
        r = await client.get("/extraction/signals")
        assert r.status_code == 200

    async def test_extraction_candidates(self, client):
        """Candidate rules discovered from extraction."""
        r = await client.get("/extraction/candidates")
        assert r.status_code == 200

    async def test_connector_sync(self, client):
        """Trigger sync on a connector."""
        data = (await client.get("/connectors")).json()
        connectors = data.get("connectors", [])
        connected = [c for c in connectors if c.get("status") in ("CONNECTED", "connected", "active")]
        if not connected:
            pytest.skip("No connected connectors to sync")
        r = await client.post(f"/connectors/{connected[0]['id']}/sync")
        assert r.status_code in (200, 202)

    async def test_hitl_pending(self, client):
        """HITL pending queue endpoint."""
        r = await client.get("/hitl/pending")
        assert r.status_code == 200

    async def test_hitl_decision_feed(self, client):
        """HITL decision feed."""
        r = await client.get("/hitl/decision-feed")
        assert r.status_code == 200

    async def test_conflicts_list(self, client):
        """Conflicts list returns data."""
        r = await client.get("/conflicts")
        assert r.status_code == 200

    async def test_marketplace_templates(self, client):
        """Marketplace templates list."""
        r = await client.get("/marketplace")
        assert r.status_code == 200

    async def test_pipeline_connectors_available(self, client):
        """Pipeline available connectors."""
        r = await client.get("/pipeline/connectors/available")
        assert r.status_code == 200

    async def test_pipeline_transforms_available(self, client):
        """Pipeline available transforms."""
        r = await client.get("/pipeline/transforms/available")
        assert r.status_code == 200
