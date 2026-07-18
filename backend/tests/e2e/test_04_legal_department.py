"""
KAEOS E2E Test 04 — Legal Department
Tests Legal-specific endpoints: contracts, clauses, obligations,
cases, DSARs, patents, dashboard, and AI agents.
"""
import pytest
from .conftest import assert_dashboard


@pytest.mark.asyncio
class TestLegalDepartment:
    """Legal Department — contracts, compliance, litigation, privacy, IP."""

    async def test_legal_dashboard(self, client):
        """Legal dashboard returns aggregate metrics."""
        await assert_dashboard(client, "/legal/dashboard")

    async def test_legal_matters(self, client):
        """Legal matters list."""
        r = await client.get("/legal/matters")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    async def test_legal_contracts(self, client):
        """Contracts list returns seeded contracts."""
        r = await client.get("/legal/contracts")
        assert r.status_code == 200
        contracts = r.json()
        assert isinstance(contracts, list)
        assert len(contracts) > 0, "Expected seeded contracts"

    async def test_legal_contract_clauses(self, client):
        """Contract detail returns clauses."""
        contracts = (await client.get("/legal/contracts")).json()
        if contracts:
            contract_id = contracts[0]["id"]
            r = await client.get(f"/legal/contracts/{contract_id}/clauses")
            assert r.status_code == 200

    async def test_legal_contract_review_agent(self, client, has_ollama):
        """Contract review AI agent runs on a contract (uses real Ollama)."""
        contracts = (await client.get("/legal/contracts")).json()
        if not contracts:
            pytest.skip("No contracts to review")
        r = await client.post(f"/legal/contracts/{contracts[0]['id']}/review")
        assert r.status_code == 200

    async def test_legal_obligations(self, client):
        """Compliance obligations list."""
        r = await client.get("/legal/compliance/obligations")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    async def test_legal_compliance_audit_agent(self, client, has_ollama):
        """Compliance audit AI agent runs on an obligation."""
        obligations = (await client.get("/legal/compliance/obligations")).json()
        if not obligations:
            pytest.skip("No obligations to audit")
        r = await client.post(f"/legal/compliance/obligations/{obligations[0]['id']}/audit")
        assert r.status_code == 200

    async def test_legal_cases(self, client):
        """Litigation cases list."""
        r = await client.get("/legal/cases")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    async def test_legal_litigation_agent(self, client, has_ollama):
        """Litigation evaluation AI agent."""
        cases = (await client.get("/legal/cases")).json()
        if not cases:
            pytest.skip("No cases to evaluate")
        r = await client.post(f"/legal/cases/{cases[0]['id']}/evaluate")
        assert r.status_code == 200

    async def test_legal_dsars(self, client):
        """Privacy DSARs list."""
        r = await client.get("/legal/privacy/dsars")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    async def test_legal_dsar_agent(self, client, has_ollama):
        """Privacy DSAR validation AI agent."""
        dsars = (await client.get("/legal/privacy/dsars")).json()
        if not dsars:
            pytest.skip("No DSARs to validate")
        r = await client.post(f"/legal/privacy/dsars/{dsars[0]['id']}/validate")
        assert r.status_code == 200

    async def test_legal_patents(self, client):
        """IP patents list."""
        r = await client.get("/legal/ip/patents")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    async def test_legal_patent_eval_agent(self, client, has_ollama):
        """Patent evaluation AI agent."""
        patents = (await client.get("/legal/ip/patents")).json()
        if not patents:
            pytest.skip("No patents to evaluate")
        r = await client.post(f"/legal/ip/patents/{patents[0]['id']}/evaluate")
        assert r.status_code == 200
