"""Vendor contract lane for the bespoke per-department connectors (mocked).

The real vendor sandboxes (Intuit, Xero, NetSuite, GitHub, Epic FHIR, Coupa)
cannot be exercised from CI, so this lane pins the CONTRACT each connector
promises instead: the exact URL and auth headers it sends, the documented
response shape it parses, and the graceful failure paths the pull mesh depends
on. httpx.MockTransport stands in for the vendor and guarded_async_client is
swapped per test, so no DNS or socket is ever touched. A pass against the live
vendor sandboxes remains a deliberate credentialed follow-up (see
KNOWN_LIMITATIONS) - this makes the code side of the contract provable today.
"""
from typing import Callable

import httpx
import pytest

from app.finance.connectors.accounting_sync import AccountingSyncConnector
from app.engineering.connectors.issue_tracker import GitHubIssueTrackerConnector
from app.healthcare.connectors.ehr_sync import EHRSyncConnector
from app.procurement.connectors.po_sync import ProcurementSyncConnector
from app.services.vendor_adapters.bespoke_bridge import BESPOKE_ADAPTERS


def _mock_guarded(handler: Callable[[httpx.Request], httpx.Response]):
    """A drop-in for guarded_async_client backed by httpx.MockTransport."""
    def factory(**_kw):
        return httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return factory


# ── AccountingSyncConnector ──────────────────────────────────────────────────

QB_CREDS = {"access_token": "qb-token", "realm_id": "R123"}


@pytest.mark.asyncio
async def test_quickbooks_invoice_contract(monkeypatch):
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        assert req.url.host == "quickbooks.api.intuit.com"
        assert req.url.path == "/v3/company/R123/query"
        assert req.headers["Authorization"] == "Bearer qb-token"
        assert req.url.params["minorversion"] == "65"
        assert req.url.params["query"] == "select * from Bill"
        return httpx.Response(200, json={
            "QueryResponse": {"Bill": [{"Id": "77", "TotalAmt": 120.5}]}})

    monkeypatch.setattr("app.finance.connectors.accounting_sync.guarded_async_client",
                        _mock_guarded(handler))
    conn = AccountingSyncConnector("t1", "quickbooks", QB_CREDS)
    bills = await conn.sync_invoices()
    assert bills == [{"Id": "77", "TotalAmt": 120.5}]
    assert len(seen) == 1


@pytest.mark.asyncio
async def test_xero_requires_org_scope_and_filters_payables(monkeypatch):
    # Xero without the organisation scope header must refuse at construction:
    # an unscoped call would hit whichever org the token defaults to.
    with pytest.raises(ValueError):
        AccountingSyncConnector("t1", "xero", {"access_token": "x"})

    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.host == "api.xero.com"
        assert req.url.path == "/api.xro/2.0/Invoices"
        assert req.headers["Xero-tenant-id"] == "org-9"
        assert req.url.params["where"] == 'Type=="ACCPAY"'
        return httpx.Response(200, json={"Invoices": [{"InvoiceID": "iv-1"}]})

    monkeypatch.setattr("app.finance.connectors.accounting_sync.guarded_async_client",
                        _mock_guarded(handler))
    conn = AccountingSyncConnector(
        "t1", "xero", {"access_token": "x", "xero_tenant_id": "org-9"})
    assert await conn.sync_invoices() == [{"InvoiceID": "iv-1"}]


@pytest.mark.asyncio
async def test_netsuite_urls_are_account_scoped(monkeypatch):
    with pytest.raises(ValueError):
        AccountingSyncConnector("t1", "netsuite", {"access_token": "n"})

    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.host == "acme1.suitetalk.api.netsuite.com"
        assert req.url.path == "/services/rest/record/v1/vendorBill"
        return httpx.Response(200, json={"items": [{"id": "vb-1"}]})

    monkeypatch.setattr("app.finance.connectors.accounting_sync.guarded_async_client",
                        _mock_guarded(handler))
    acct = AccountingSyncConnector(
        "t1", "netsuite", {"access_token": "n", "account_id": "acme1"})
    assert await acct.sync_invoices() == [{"id": "vb-1"}]


@pytest.mark.asyncio
async def test_accounting_test_connection_fails_gracefully(monkeypatch):
    """A bad credential returns False - it must never raise into the mesh."""
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"fault": "invalid token"})

    monkeypatch.setattr("app.finance.connectors.accounting_sync.guarded_async_client",
                        _mock_guarded(handler))
    conn = AccountingSyncConnector("t1", "quickbooks", QB_CREDS)
    assert await conn.test_connection() is False


# ── GitHubIssueTrackerConnector ──────────────────────────────────────────────

GH_CREDS = {"token": "gh-token", "owner": "kaeos", "repo": "core"}


@pytest.mark.asyncio
async def test_github_issue_contract_filters_pull_requests(monkeypatch):
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.host == "api.github.com"
        assert req.url.path == "/repos/kaeos/core/issues"
        assert req.headers["Authorization"] == "Bearer gh-token"
        assert req.headers["Accept"] == "application/vnd.github+json"
        assert req.headers["X-GitHub-Api-Version"] == "2022-11-28"
        assert req.url.params["state"] == "open"
        # GitHub's /issues endpoint interleaves PRs; the connector must drop them.
        return httpx.Response(200, json=[
            {"number": 1, "title": "real issue"},
            {"number": 2, "title": "a PR", "pull_request": {"url": "..."}},
        ])

    monkeypatch.setattr("app.engineering.connectors.issue_tracker.guarded_async_client",
                        _mock_guarded(handler))
    conn = GitHubIssueTrackerConnector("t1", GH_CREDS)
    issues = await conn.sync_open_issues()
    assert [i["number"] for i in issues] == [1]


@pytest.mark.asyncio
async def test_github_workflow_runs_unwrap_envelope(monkeypatch):
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path == "/repos/kaeos/core/actions/runs"
        return httpx.Response(200, json={
            "total_count": 1, "workflow_runs": [{"id": 9, "status": "completed"}]})

    monkeypatch.setattr("app.engineering.connectors.issue_tracker.guarded_async_client",
                        _mock_guarded(handler))
    conn = GitHubIssueTrackerConnector("t1", GH_CREDS)
    assert await conn.sync_workflow_runs() == [{"id": 9, "status": "completed"}]


# ── EHRSyncConnector (FHIR) ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ehr_fhir_bundle_contract(monkeypatch):
    def handler(req: httpx.Request) -> httpx.Response:
        assert str(req.url).startswith("https://fhir.example.org/R4/Patient")
        assert req.headers["Accept"] == "application/fhir+json"
        assert req.headers["Authorization"] == "Bearer ehr-token"
        # A FHIR Bundle: entries without a resource key must be skipped.
        return httpx.Response(200, json={
            "resourceType": "Bundle",
            "entry": [
                {"resource": {"resourceType": "Patient", "id": "p1"}},
                {"fullUrl": "urn:no-resource-here"},
            ],
        })

    monkeypatch.setattr("app.healthcare.connectors.ehr_sync.guarded_async_client",
                        _mock_guarded(handler))
    conn = EHRSyncConnector(
        "t1", "epic",
        {"access_token": "ehr-token", "fhir_base_url": "https://fhir.example.org/R4"})
    patients = await conn.sync_patients()
    assert patients == [{"resourceType": "Patient", "id": "p1"}]


# ── ProcurementSyncConnector ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_coupa_purchase_order_contract(monkeypatch):
    with pytest.raises(ValueError):
        ProcurementSyncConnector("t1", "coupa", {"access_token": "c"})

    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.host == "acme.coupahost.com"
        assert req.url.path == "/api/purchase_orders"
        assert req.headers["Authorization"] == "Bearer c-token"
        # Coupa may return a bare list or an envelope; the connector handles both.
        return httpx.Response(200, json=[{"id": 501, "status": "issued"}])

    monkeypatch.setattr("app.procurement.connectors.po_sync.guarded_async_client",
                        _mock_guarded(handler))
    conn = ProcurementSyncConnector(
        "t1", "coupa", {"access_token": "c-token", "instance": "acme"})
    assert await conn.sync_purchase_orders() == [{"id": 501, "status": "issued"}]


# ── The bridge: what the scheduler actually runs ─────────────────────────────

@pytest.mark.asyncio
async def test_bridge_normalizes_and_caps_batch(monkeypatch):
    """BESPOKE_ADAPTERS['quickbooks'].fetch is the exact scheduler path: both
    sync methods run, each capped at batch_size, normalized to signal shape."""
    def handler(req: httpx.Request) -> httpx.Response:
        q = req.url.params.get("query", "")
        if "Bill" in q:
            return httpx.Response(200, json={"QueryResponse": {"Bill": [
                {"Id": "b1"}, {"Id": "b2"}]}})
        return httpx.Response(200, json={"QueryResponse": {"Invoice": [
            {"Id": "i1"}, {"Id": "i2"}]}})

    monkeypatch.setattr("app.finance.connectors.accounting_sync.guarded_async_client",
                        _mock_guarded(handler))
    adapter = BESPOKE_ADAPTERS["quickbooks"]
    signals = await adapter.fetch(
        {"tenant_id": "t1", "batch_size": 1, **QB_CREDS}, QB_CREDS)
    # Two methods (invoices + receivables), one record each after the cap.
    assert len(signals) == 2
    assert {s["external_id"] for s in signals} == {"b1", "i1"}
    for s in signals:
        assert s["entity"] == "invoice"
        assert s["domain"] == "finance"
        assert s["authority"] == 0.95
        assert s["pii"] is False


@pytest.mark.asyncio
async def test_bridge_is_graceful_per_method(monkeypatch):
    """One failing vendor endpoint loses only its own records, never raises
    into the mesh - the other method's records still arrive."""
    def handler(req: httpx.Request) -> httpx.Response:
        q = req.url.params.get("query", "")
        if "Bill" in q:
            return httpx.Response(500, json={"fault": "vendor down"})
        return httpx.Response(200, json={"QueryResponse": {"Invoice": [{"Id": "i1"}]}})

    monkeypatch.setattr("app.finance.connectors.accounting_sync.guarded_async_client",
                        _mock_guarded(handler))
    adapter = BESPOKE_ADAPTERS["quickbooks"]
    signals = await adapter.fetch(
        {"tenant_id": "t1", "batch_size": 25, **QB_CREDS}, QB_CREDS)
    assert {s["external_id"] for s in signals} == {"i1"}


@pytest.mark.asyncio
async def test_bridge_test_reports_failure_without_raising(monkeypatch):
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"fault": "expired"})

    monkeypatch.setattr("app.finance.connectors.accounting_sync.guarded_async_client",
                        _mock_guarded(handler))
    adapter = BESPOKE_ADAPTERS["quickbooks"]
    result = await adapter.test({"tenant_id": "t1", **QB_CREDS}, QB_CREDS)
    assert result["ok"] is False
