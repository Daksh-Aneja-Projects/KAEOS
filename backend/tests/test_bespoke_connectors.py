"""The per-department bespoke connectors are bridged into the pull catalog.

Finance accounting (QuickBooks/Xero/NetSuite), the engineering issue tracker, and
healthcare EHR shipped real endpoint logic + unit tests but no invocation path.
BespokeConnectorAdapter wraps each so it satisfies the pull contract and inherits
the scheduler + ConnectorCredential + the M15 cursor, reusing the connector's code
and FAILING GRACEFULLY (one bad connector can't 500 the mesh)."""
import pytest

from app.services.vendor_adapters.bespoke_bridge import BespokeConnectorAdapter


class _FakeConn:
    async def test_connection(self):
        return True

    async def sync_a(self):
        return [{"id": "1", "amount": 100}, {"id": "2", "amount": 200}]

    async def sync_b(self):
        raise RuntimeError("upstream 500")


@pytest.mark.asyncio
async def test_bridge_normalizes_and_a_failing_sync_is_skipped():
    a = BespokeConnectorAdapter(
        factory=lambda c, s: _FakeConn(), sync_methods=["sync_a", "sync_b"],
        entity="invoice", domain="finance", authority=0.95)
    sigs = await a.fetch({"batch_size": 5}, {})
    assert len(sigs) == 2, "sync_a's records land; sync_b fails gracefully"
    assert sigs[0]["external_id"] == "1"
    assert sigs[0]["entity"] == "invoice" and sigs[0]["domain"] == "finance"


@pytest.mark.asyncio
async def test_construct_failure_never_raises():
    def _boom(config, secrets):
        raise ValueError("no credentials on file")

    a = BespokeConnectorAdapter(factory=_boom, sync_methods=["sync_a"],
                                entity="x", domain="y")
    assert await a.fetch({}, {}) == []
    assert (await a.test({}, {}))["ok"] is False


def test_new_providers_are_registered_and_docusign_stays_the_wired_one():
    from app.services.vendor_adapters.hr_finance import DocuSignAdapter
    from app.services.vendor_adapters.registry import VENDOR_ADAPTERS
    for p in ("quickbooks", "xero", "netsuite_accounting", "issue_tracker", "ehr",
              "coupa", "ariba", "netsuite_procurement"):
        assert p in VENDOR_ADAPTERS, f"{p} must be in the pull catalog"
    # docusign is NOT re-bridged — the original wired adapter stays.
    assert isinstance(VENDOR_ADAPTERS["docusign"], DocuSignAdapter)


# ── credit_bureau: request-shaped, wired into underwriting intake ────────────
@pytest.mark.asyncio
async def test_bureau_score_pulled_when_a_bureau_is_configured(db, monkeypatch):
    from app.lending.api.v1 import router as R
    from app.models.domain import ConnectorCredential

    db.add(ConnectorCredential(connector_id="c1", tenant_id="t_cb",
                               provider="experian", config={}, secrets_encrypted="enc"))
    await db.commit()

    class _Conn:
        def __init__(self, *a, **k):
            pass

        async def pull_report(self, ref):
            return {"status": "ok", "score": 720}

    monkeypatch.setattr("app.lending.connectors.credit_bureau.CreditBureauConnector", _Conn)
    monkeypatch.setattr("app.services.live_connectors.decrypt_secrets", lambda x: {"api_key": "k"})

    assert await R._pull_bureau_score(db, "t_cb", "APP-1") == 720


@pytest.mark.asyncio
async def test_no_bureau_configured_falls_back_to_none_never_fabricates(db):
    from app.lending.api.v1 import router as R
    assert await R._pull_bureau_score(db, "t_none", "APP-1") is None
    assert await R._pull_bureau_score(db, "t_none", None) is None
