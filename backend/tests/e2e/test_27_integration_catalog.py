"""
KAEOS E2E Test 27 — Integration Catalog

The connector mesh grew from 5 live adapters (jira, salesforce, workday, sap,
generic_rest) to 22, closing the biggest gap: the Engineering domain shipped
with no integrations at all despite being the largest slice of enterprise AI
spend.

These tests assert the catalog is real and, critically, that every adapter FAILS
GRACEFULLY — a bad credential must return ok:false with a diagnostic, never a
500. A connector mesh that 500s on a typo is not enterprise software.
"""
import pytest

# Providers that need no config to attempt a connection, so a bad-credential
# test exercises the adapter's real error path.
NO_CONFIG_PROVIDERS = ["pagerduty", "datadog", "hubspot", "stripe", "intercom",
                       "greenhouse", "notion", "microsoft_graph"]

EXPECTED_BY_DOMAIN = {
    "engineering": {"github", "gitlab", "pagerduty", "datadog", "sentry", "jira"},
    "support": {"zendesk", "intercom"},
    "sales": {"hubspot", "salesforce"},
    "hr": {"bamboohr", "greenhouse", "workday"},
    "finance": {"stripe", "sap"},
    "legal": {"docusign"},
    "operations": {"servicenow"},
}


@pytest.mark.asyncio
class TestProviderCatalog:
    """GET /connectors/providers — the capability listing."""

    async def test_catalog_lists_providers(self, client):
        r = await client.get("/connectors/providers")
        assert r.status_code == 200, f"catalog failed: {r.text[:200]}"
        data = r.json()
        assert data["total"] >= 20, f"expected a broad catalog, got {data['total']}"
        assert isinstance(data["providers"], list)
        for key in ("id", "domain", "entity", "authority", "handles_pii", "required_config"):
            assert key in data["providers"][0], f"Missing '{key}'"

    async def test_catalog_never_leaks_secrets(self, client):
        """The catalog is a public capability listing — no credentials, ever."""
        r = await client.get("/connectors/providers")
        body = r.text.lower()
        for forbidden in ("api_key\":", "secret", "token\":", "password"):
            assert forbidden not in body, f"catalog leaked '{forbidden}'"

    async def test_every_domain_has_integrations(self, client):
        """Regression: Engineering had zero connectors when the domain shipped."""
        by_domain = (await client.get("/connectors/providers")).json()["by_domain"]
        for domain, expected in EXPECTED_BY_DOMAIN.items():
            assert domain in by_domain, f"No integrations for domain '{domain}'"
            missing = expected - set(by_domain[domain])
            assert not missing, f"{domain} missing adapters: {sorted(missing)}"

    async def test_engineering_is_best_covered(self, client):
        """Engineering + IT ops is ~65% of departmental spend; it must be deep."""
        by_domain = (await client.get("/connectors/providers")).json()["by_domain"]
        assert len(by_domain.get("engineering", [])) >= 5, (
            "Engineering is the largest spend domain and needs real coverage"
        )

    async def test_systems_of_record_outrank_chat(self, client):
        """
        Authority weighting must reflect epistemic reality: an HRIS or incident
        system is a system of record; Slack is people talking.
        """
        providers = {p["id"]: p for p in (await client.get("/connectors/providers")).json()["providers"]}
        assert providers["slack"]["authority"] < providers["bamboohr"]["authority"]
        assert providers["slack"]["authority"] < providers["pagerduty"]["authority"]
        assert providers["notion"]["authority"] < providers["stripe"]["authority"]

    async def test_pii_flags_are_set_where_expected(self, client):
        providers = {p["id"]: p for p in (await client.get("/connectors/providers")).json()["providers"]}
        for pid in ("bamboohr", "greenhouse", "zendesk", "slack"):
            assert providers[pid]["handles_pii"] is True, f"{pid} must be flagged as PII-bearing"
        for pid in ("github", "datadog"):
            assert providers[pid]["handles_pii"] is False


@pytest.mark.asyncio
class TestNewAdaptersFailGracefully:
    """
    Every adapter must survive bad credentials with ok:false — never a 500.
    """

    async def _connector_id(self, client) -> str:
        conns = (await client.get("/connectors")).json().get("connectors", [])
        assert conns, "No connectors seeded"
        return conns[0]["id"]

    @pytest.mark.parametrize("provider", NO_CONFIG_PROVIDERS)
    async def test_adapter_bad_credentials_is_graceful(self, client, provider):
        cid = await self._connector_id(client)
        try:
            store = await client.put(f"/connectors/{cid}/credentials", json={
                "provider": provider,
                "config": {},
                "secrets": {
                    "api_key": "kaeos-e2e-invalid", "app_key": "kaeos-e2e-invalid",
                    "access_token": "kaeos-e2e-invalid", "token": "kaeos-e2e-invalid",
                    "secret_key": "kaeos-e2e-invalid", "bot_token": "kaeos-e2e-invalid",
                },
            })
            assert store.status_code == 200, f"{provider} store failed: {store.text[:200]}"

            r = await client.post(f"/connectors/{cid}/test")
            assert r.status_code == 200, (
                f"{provider} must not 500 on bad credentials — got {r.status_code}: {r.text[:200]}"
            )
            body = r.json()
            assert body.get("ok") is False, f"{provider} accepted an invalid credential: {body}"
            assert body.get("detail"), f"{provider} gave no diagnostic detail"
        finally:
            await client.delete(f"/connectors/{cid}/credentials")

    async def test_config_validation_rejects_missing_keys(self, client):
        """github needs owner+repo; storing without them must be rejected up front."""
        cid = await self._connector_id(client)
        r = await client.put(f"/connectors/{cid}/credentials", json={
            "provider": "github", "config": {}, "secrets": {"token": "x"},
        })
        assert r.status_code == 400, f"expected 400 for missing config, got {r.status_code}"
        assert "owner" in r.text or "repo" in r.text

    async def test_unknown_provider_rejected(self, client):
        cid = await self._connector_id(client)
        r = await client.put(f"/connectors/{cid}/credentials", json={
            "provider": "not-a-real-vendor", "config": {}, "secrets": {},
        })
        assert r.status_code == 400
