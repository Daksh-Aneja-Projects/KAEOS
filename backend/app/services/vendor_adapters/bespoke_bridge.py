"""Bridge the per-department bespoke connectors into the pull catalog.

Finance/engineering/healthcare/legal each shipped a rich, multi-provider,
multi-resource sync connector (AccountingSyncConnector over QuickBooks/Xero/
NetSuite, IssueTrackerConnector, EHRSyncConnector, DocuSignConnector) with real
endpoint + auth logic and unit tests — but zero invocation path, so the scheduler
never pulled them. Rather than rewrite that logic as single-endpoint REST
adapters (and risk it), this bridge WRAPS each connector so it satisfies the pull
contract (``test`` / ``fetch``) and inherits the scheduler, ConnectorCredential
and the M15 cursor plumbing, reusing the connector's own code unchanged.

The connectors talk to real external APIs that cannot be validated here, so the
bridge FAILS GRACEFULLY: a construction or sync error yields [] (or a failed
test), never a raise — one misconfigured connector cannot 500 the mesh or block
another tenant's pull. tenant_id is threaded in via ``config['tenant_id']``.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Sequence

from .base import _fmt

logger = logging.getLogger(__name__)


class BespokeConnectorAdapter:
    """Adapt a bespoke per-department connector to the vendor-adapter contract."""

    def __init__(self, *, factory: Callable[[Dict[str, Any], Dict[str, Any]], Any],
                 sync_methods: Sequence[str], entity: str, domain: str,
                 authority: float = 0.9, pii: bool = False):
        self._factory = factory                 # (config, secrets) -> connector
        self._sync_methods = list(sync_methods)  # connector methods returning list[dict]
        self.entity, self.domain, self.authority, self.pii = entity, domain, authority, pii

    async def test(self, config, secrets) -> Dict[str, Any]:
        try:
            conn = self._factory(config, secrets)
            ok = await conn.test_connection()
            return {"ok": bool(ok), "detail": "Connected" if ok else "Connection test failed"}
        except Exception as e:  # never raise out of a connection test
            return {"ok": False, "detail": f"{type(e).__name__}: {str(e)[:120]}"}

    async def fetch(self, config, secrets) -> List[Dict[str, Any]]:
        try:
            conn = self._factory(config, secrets)
        except Exception as e:
            logger.warning("[BespokeBridge] %s construct failed: %s", self.entity, e)
            return []
        limit = int(config.get("batch_size", 25))
        out: List[Dict[str, Any]] = []
        for method in self._sync_methods:
            try:
                records = await getattr(conn, method)()
            except Exception as e:
                logger.warning("[BespokeBridge] %s.%s failed: %s", self.entity, method, e)
                continue
            for r in (records or [])[:limit]:
                if isinstance(r, dict):
                    out.append(self._to_signal(r))
        return out

    def _to_signal(self, r: Dict[str, Any]) -> Dict[str, Any]:
        ext = r.get("id") or r.get("Id") or r.get("number") or r.get("EnvelopeId") or ""
        return {
            "external_id": str(ext),
            "entity": self.entity,
            "summary": _fmt(r, keys=5),
            "domain": self.domain,
            "authority": self.authority,
            "pii": self.pii,
        }


# ── Per-connector factories. The scheduler calls fetch_records(cred.provider, ...)
# so the PROVIDER is the registry key; each factory binds it. config carries
# tenant_id (threaded by the pull), secrets the decrypted credentials. ──

def _accounting_factory(provider):
    def make(config, secrets):
        from app.finance.connectors.accounting_sync import AccountingSyncConnector
        return AccountingSyncConnector(
            config.get("tenant_id", ""), provider, {**(config or {}), **(secrets or {})})
    return make


def _issue_tracker_factory(config, secrets):
    from app.engineering.connectors.issue_tracker import GitHubIssueTrackerConnector
    return GitHubIssueTrackerConnector(config.get("tenant_id", ""), {**(config or {}), **(secrets or {})})


def _ehr_factory(provider):
    def make(config, secrets):
        from app.healthcare.connectors.ehr_sync import EHRSyncConnector
        return EHRSyncConnector(
            config.get("tenant_id", ""), provider, {**(config or {}), **(secrets or {})})
    return make


def _procurement_factory(provider):
    def make(config, secrets):
        from app.procurement.connectors.po_sync import ProcurementSyncConnector
        return ProcurementSyncConnector(
            config.get("tenant_id", ""), provider, {**(config or {}), **(secrets or {})})
    return make


# Only genuinely-new integrations are registered. docusign is intentionally
# absent: it duplicates the already-wired DocuSignAdapter. credit_bureau is
# per-request (underwriting intake), not a periodic list-sync, so it is not a
# pull-catalog entry. These are pull-READY but not validated against the real
# vendor APIs — see KNOWN_LIMITATIONS.
_ACCT = ["sync_invoices", "sync_receivables"]
BESPOKE_ADAPTERS: Dict[str, BespokeConnectorAdapter] = {
    "quickbooks": BespokeConnectorAdapter(
        factory=_accounting_factory("quickbooks"), sync_methods=_ACCT,
        entity="invoice", domain="finance", authority=0.95),
    "xero": BespokeConnectorAdapter(
        factory=_accounting_factory("xero"), sync_methods=_ACCT,
        entity="invoice", domain="finance", authority=0.95),
    "netsuite_accounting": BespokeConnectorAdapter(
        factory=_accounting_factory("netsuite"), sync_methods=_ACCT,
        entity="invoice", domain="finance", authority=0.95),
    "issue_tracker": BespokeConnectorAdapter(
        factory=_issue_tracker_factory,
        sync_methods=["sync_open_issues", "sync_pull_requests", "sync_workflow_runs"],
        entity="issue", domain="engineering", authority=0.9),
    "ehr": BespokeConnectorAdapter(
        factory=_ehr_factory("epic"), sync_methods=["sync_patients", "sync_encounters"],
        entity="clinical_record", domain="healthcare", authority=0.95, pii=True),
    # Procurement — purchase orders (Coupa / Ariba / NetSuite).
    "coupa": BespokeConnectorAdapter(
        factory=_procurement_factory("coupa"), sync_methods=["sync_purchase_orders"],
        entity="purchase_order", domain="procurement", authority=0.9),
    "ariba": BespokeConnectorAdapter(
        factory=_procurement_factory("ariba"), sync_methods=["sync_purchase_orders"],
        entity="purchase_order", domain="procurement", authority=0.9),
    "netsuite_procurement": BespokeConnectorAdapter(
        factory=_procurement_factory("netsuite"), sync_methods=["sync_purchase_orders"],
        entity="purchase_order", domain="procurement", authority=0.9),
}
