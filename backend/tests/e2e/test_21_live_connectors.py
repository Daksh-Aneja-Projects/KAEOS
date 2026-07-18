"""
KAEOS E2E Test 21 — Live Connector Integrations
Tests the self-service live-integration flow: store credentials (encrypted at
rest, write-only), masked status, test-connection, live sync pulling real
records over HTTP, credential deletion, and fallback to the demo feed.

The generic REST provider is exercised against a real public API
(jsonplaceholder.typicode.com) so the live path is genuinely end-to-end.
"""
import pytest


async def _pick_connector(client, prefer_status=None):
    data = (await client.get("/connectors")).json()
    conns = data.get("connectors", [])
    if prefer_status:
        preferred = [c for c in conns if c.get("status") == prefer_status]
        if preferred:
            return preferred[0]
    return conns[0] if conns else None


@pytest.mark.asyncio
class TestCredentialLifecycle:
    """Store → status(masked) → test → sync(live) → delete → fallback."""

    async def test_01_status_unconfigured(self, client):
        """Unconfigured connector reports provider inference + required config."""
        conn = await _pick_connector(client)
        assert conn, "No connectors seeded"
        r = await client.get(f"/connectors/{conn['id']}/credentials")
        assert r.status_code == 200
        body = r.json()
        # May be configured from a previous run — both shapes are valid
        assert "configured" in body
        if not body["configured"]:
            assert body.get("inferred_provider")
            assert isinstance(body.get("required_config"), list)

    async def test_02_store_credentials_validation(self, client):
        """Missing required config is rejected with 400."""
        conn = await _pick_connector(client)
        r = await client.put(f"/connectors/{conn['id']}/credentials", json={
            "provider": "jira", "config": {}, "secrets": {"email": "x", "api_token": "y"},
        })
        assert r.status_code == 400
        assert "base_url" in r.json()["detail"]

    async def test_03_unknown_provider_rejected(self, client):
        conn = await _pick_connector(client)
        r = await client.put(f"/connectors/{conn['id']}/credentials", json={
            "provider": "not_a_provider", "config": {"base_url": "https://x"}, "secrets": {},
        })
        assert r.status_code == 400

    async def test_04_full_live_flow_generic_rest(self, client):
        """Real end-to-end: credentials → test → connect → LIVE sync from a public API."""
        conn = await _pick_connector(client)
        cid = conn["id"]

        # 1. Store credentials for a real public JSON API
        r = await client.put(f"/connectors/{cid}/credentials", json={
            "provider": "generic_rest",
            "config": {
                "base_url": "https://jsonplaceholder.typicode.com",
                "endpoint": "/users",
                "batch_size": 5,
                "entity_name": "user",
                "domain": "general",
            },
            "secrets": {},
        })
        assert r.status_code == 200, f"{r.status_code}: {r.text[:200]}"
        assert r.json()["status"] == "CREDENTIALS_STORED"

        # 2. Masked status shows configuration but never secret values
        r2 = await client.get(f"/connectors/{cid}/credentials")
        body = r2.json()
        assert body["configured"] is True
        assert body["provider"] == "generic_rest"
        assert "secrets" not in body, "Status endpoint must never return secret values"

        # 3. Live connection test against the real endpoint
        r3 = await client.post(f"/connectors/{cid}/test")
        assert r3.status_code == 200, f"{r3.status_code}: {r3.text[:200]}"
        if not r3.json()["ok"]:
            pytest.skip(f"Public API unreachable from this network: {r3.json()['detail']}")

        # 4. Connect, then sync — must run in LIVE mode and create signals
        await client.post(f"/connectors/{cid}/connect")
        r4 = await client.post(f"/connectors/{cid}/sync")
        assert r4.status_code == 200, f"{r4.status_code}: {r4.text[:300]}"
        sync = r4.json()
        assert sync["mode"] == "LIVE", f"Expected LIVE sync, got {sync}"
        assert sync["events_synced"] > 0
        assert sync["signals_created"] > 0

        # 5. The live records surface as signals in the connector feed
        r5 = await client.get(f"/connectors/{cid}/feed?limit=10")
        events = r5.json().get("events", [])
        assert any(e.get("signal_type") == "LIVE_SYNC" for e in events), \
            "Live-sync signals should appear in the feed"

        TestCredentialLifecycle._live_connector_id = cid

    async def test_05_connectors_list_shows_live_badge(self, client):
        cid = getattr(TestCredentialLifecycle, "_live_connector_id", None)
        if not cid:
            pytest.skip("Live flow did not run")
        data = (await client.get("/connectors")).json()
        match = [c for c in data["connectors"] if c["id"] == cid]
        assert match and match[0].get("live_integration"), \
            "Connector list should expose live_integration for configured connectors"
        assert "secrets" not in str(match[0].get("live_integration"))

    async def test_06_delete_credentials_falls_back_to_demo(self, client):
        cid = getattr(TestCredentialLifecycle, "_live_connector_id", None)
        if not cid:
            pytest.skip("Live flow did not run")
        r = await client.delete(f"/connectors/{cid}/credentials")
        assert r.status_code == 200
        # Sync now uses the simulated demo path again
        r2 = await client.post(f"/connectors/{cid}/sync")
        assert r2.status_code == 200
        assert r2.json()["mode"] == "SIMULATED"

    async def test_07_test_without_credentials_400(self, client):
        cid = getattr(TestCredentialLifecycle, "_live_connector_id", None)
        if not cid:
            pytest.skip("Live flow did not run")
        r = await client.post(f"/connectors/{cid}/test")
        assert r.status_code == 400


@pytest.mark.asyncio
class TestProviderAdapters:
    """Vendor adapters fail gracefully (structured result, never a 500) with bad creds."""

    async def _store_and_test(self, client, provider, config, secrets):
        conn = await _pick_connector(client)
        cid = conn["id"]
        r = await client.put(f"/connectors/{cid}/credentials", json={
            "provider": provider, "config": config, "secrets": secrets,
        })
        assert r.status_code == 200, f"store {provider} → {r.status_code}: {r.text[:200]}"
        r2 = await client.post(f"/connectors/{cid}/test")
        assert r2.status_code == 200, f"test {provider} → {r2.status_code}: {r2.text[:200]}"
        body = r2.json()
        assert body["ok"] is False, f"{provider} with fake creds should not authenticate"
        assert body["detail"], "Failure must carry a diagnostic detail"
        # Clean up so later tests see an unconfigured/demo connector
        await client.delete(f"/connectors/{cid}/credentials")

    async def test_jira_adapter_graceful_failure(self, client):
        await self._store_and_test(client, "jira",
            {"base_url": "https://kaeos-e2e-nonexistent.atlassian.net"},
            {"email": "e2e@example.com", "api_token": "not-a-real-token"})

    async def test_salesforce_adapter_graceful_failure(self, client):
        await self._store_and_test(client, "salesforce",
            {"instance_url": "https://kaeos-e2e-nonexistent.my.salesforce.com"},
            {"client_id": "fake", "client_secret": "fake"})

    async def test_workday_adapter_graceful_failure(self, client):
        await self._store_and_test(client, "workday",
            {"report_url": "https://kaeos-e2e-nonexistent.workday.com/ccx/service/report"},
            {"username": "isu_fake", "password": "fake"})

    async def test_sap_adapter_graceful_failure(self, client):
        await self._store_and_test(client, "sap",
            {"service_url": "https://kaeos-e2e-nonexistent.sap.example/odata/API_TEST"},
            {"api_key": "fake"})
