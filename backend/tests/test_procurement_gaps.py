"""Procurement gap-fix coverage: gated agent wiring (sourcing_agent /
spend_guard_agent), the vendors query rewrite (VendorContract-based, not
PO-grouped), analytics, workflow specs, the Coupa/NetSuite/Ariba connector,
and seed idempotency.
"""
import os
import uuid
from datetime import date, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.operations.models.procurement import (
    POLineItem, ProcurementStatus, PurchaseOrder, PurchaseRequest,
)
from app.operations.models.vendors import VendorContract, VendorPerformance
from app.procurement.connectors.po_sync import ProcurementSyncConnector
from app.procurement.services.analytics import procurement_analytics
from app.procurement.services.workflows import SPECS as PROCUREMENT_SPECS
from app.services.llm_router import LLMRouter

TENANT = "tenant_acme"  # dev-mode default tenant (app.core.tenant._DEV_TENANT)


def _t():
    return f"tenant_procgap_{uuid.uuid4().hex[:6]}"


async def _no_provider(self, *args, **kwargs) -> bool:
    """Forces the gated pipeline's fast simulated fallback (no real model
    call), mirroring tests/test_hr_api_gated.py. Skipped under KAEOS_FAKE_LLM,
    which installs a different, mutually-exclusive fake."""
    return False


# ── Vendors: VendorContract-based, not PurchaseOrder-grouped ──────────────

async def test_vendors_endpoint_surfaces_contract_without_po(db):
    """The flagship sanctions demo: a vendor under contract with NO purchase
    order must still appear, with its contract/performance data - the
    PO-grouped query this replaces could never surface it."""
    tenant = _t()
    with_po = VendorContract(id=str(uuid.uuid4()), tenant_id=tenant, vendor_name="Has A PO Ltd",
                             service_provided="Widgets", contract_value=50000.0,
                             renewal_date=date.today() + timedelta(days=100))
    no_po = VendorContract(id=str(uuid.uuid4()), tenant_id=tenant, vendor_name="Crimson Star Trading Ltd",
                           service_provided="Industrial equipment import", contract_value=88000.0,
                           renewal_date=date.today() + timedelta(days=60))
    db.add_all([with_po, no_po])
    await db.flush()
    db.add(VendorPerformance(id=str(uuid.uuid4()), tenant_id=tenant, vendor_contract_id=with_po.id,
                             overall_performance_score=92.0))
    db.add(PurchaseOrder(id=str(uuid.uuid4()), tenant_id=tenant, po_number="PO-T-0001",
                         vendor_name="Has A PO Ltd", total_amount=1500.0,
                         status=ProcurementStatus.ORDERED))
    await db.commit()

    from app.procurement.api.v1.router import list_procurement_vendors
    rows = await list_procurement_vendors(tenant_id=tenant, db=db)
    by_name = {r["vendor"]: r for r in rows}

    assert "Crimson Star Trading Ltd" in by_name  # reachable with zero POs
    sanctioned = by_name["Crimson Star Trading Ltd"]
    assert sanctioned["po_count"] == 0
    assert sanctioned["committed_spend"] == 0
    assert sanctioned["contract_value"] == 88000.0
    assert sanctioned["renewal_date"]
    assert sanctioned["performance_score"] is None  # honesty: no sheet yet

    has_po = by_name["Has A PO Ltd"]
    assert has_po["po_count"] == 1
    assert has_po["committed_spend"] == 1500.0
    assert has_po["performance_score"] == 92.0


async def test_vendors_endpoint_tenant_scoped(db):
    tenant, other = _t(), _t()
    db.add(VendorContract(id=str(uuid.uuid4()), tenant_id=other, vendor_name="Other Tenant Vendor",
                          service_provided="X", contract_value=1.0))
    await db.commit()
    from app.procurement.api.v1.router import list_procurement_vendors
    rows = await list_procurement_vendors(tenant_id=tenant, db=db)
    assert rows == []


# ── Analytics ────────────────────────────────────────────────────────────

async def test_analytics_shape_matches_shared_contract(db):
    tenant = _t()
    result = await procurement_analytics(db, tenant, charts=True)
    assert set(result.keys()) == {"domain", "kpis", "charts", "insights"}
    assert result["domain"] == "procurement"
    assert isinstance(result["kpis"], list) and result["kpis"]
    for kpi in result["kpis"]:
        assert {"key", "label", "value", "format"} <= set(kpi.keys())
    assert isinstance(result["insights"], list) and result["insights"]


async def test_analytics_charts_false_skips_series(db):
    tenant = _t()
    result = await procurement_analytics(db, tenant, charts=False)
    assert result["charts"] == []


async def test_analytics_cycle_time_honesty_and_measurement(db):
    tenant = _t()
    # No PO cites a requisition yet -> unmeasurable, honest None + note.
    empty = await procurement_analytics(db, tenant, charts=False)
    cycle = next(k for k in empty["kpis"] if k["key"] == "cycle_time")
    assert cycle["value"] is None
    assert "note" in cycle

    # A PO citing its requisition -> a real, computed cycle time.
    req = PurchaseRequest(id=str(uuid.uuid4()), tenant_id=tenant, item_description="Widgets",
                          quantity=1, unit_price=10, total_estimated_cost=10,
                          status=ProcurementStatus.APPROVED)
    db.add(req)
    await db.flush()
    po = PurchaseOrder(id=str(uuid.uuid4()), tenant_id=tenant, purchase_request_id=req.id,
                       po_number="PO-CYCLE-1", vendor_name="V", total_amount=10,
                       status=ProcurementStatus.ORDERED)
    db.add(po)
    await db.commit()
    filled = await procurement_analytics(db, tenant, charts=False)
    cycle2 = next(k for k in filled["kpis"] if k["key"] == "cycle_time")
    assert cycle2["value"] is not None
    assert cycle2["value"] >= 0


async def test_analytics_vendor_risk_bucketing(db):
    tenant = _t()
    db.add_all([
        VendorContract(id=str(uuid.uuid4()), tenant_id=tenant, vendor_name="Renews Soon",
                       service_provided="X", contract_value=1.0,
                       renewal_date=date.today() + timedelta(days=5)),  # HIGH
        VendorContract(id=str(uuid.uuid4()), tenant_id=tenant, vendor_name="Renews Later",
                       service_provided="X", contract_value=1.0,
                       renewal_date=date.today() + timedelta(days=300)),  # LOW
    ])
    await db.commit()
    result = await procurement_analytics(db, tenant, charts=True)
    high_risk = next(k for k in result["kpis"] if k["key"] == "high_risk_vendors")
    assert high_risk["value"] == 1
    risk_chart = next(c for c in result["charts"] if c["key"] == "vendor_risk")
    labels = {i["label"] for i in risk_chart["items"]}
    assert "High" in labels and "Low" in labels


# ── Workflow specs ───────────────────────────────────────────────────────

def test_workflow_entity_types_are_globally_unique():
    """entity_type is the merge key in app.services.workflow_registry across
    every domain - a collision with Operations' purchase_request/purchase_order
    (same underlying tables) would silently clobber one domain's spec."""
    from app.operations.services.workflows import SPECS as OPERATIONS_SPECS
    assert set(PROCUREMENT_SPECS.keys()).isdisjoint(set(OPERATIONS_SPECS.keys()))


def test_po_workflow_excludes_bare_approval():
    """PENDING_APPROVAL -> APPROVED must stay off the generic transition map:
    that move is fail-closed through approve_purchase_order's four gates, and
    a bare workflow transition would bypass every one of them."""
    spec = PROCUREMENT_SPECS["procurement_purchase_order"]
    assert "APPROVED" not in spec.transitions.get("PENDING_APPROVAL", [])


async def test_requisition_transition_endpoint(async_client: AsyncClient):
    r = await async_client.post("/api/v1/procurement/requisitions", json={
        "item_description": "Test widgets", "quantity": 2, "unit_price": 5.0,
    })
    assert r.status_code == 201, r.text
    req_id = r.json()["id"]

    r = await async_client.post(f"/api/v1/procurement/requisitions/{req_id}/transition",
                                json={"to_state": "PENDING_APPROVAL"})
    assert r.status_code == 200, r.text
    assert r.json()["to_state"] == "PENDING_APPROVAL"


async def test_po_transition_rejects_bare_approval(async_client: AsyncClient):
    r = await async_client.post("/api/v1/procurement/purchase-orders", json={
        "vendor_name": "Test Vendor", "lines": [{"description": "x", "quantity": 1, "unit_price": 100}],
    })
    assert r.status_code == 201, r.text
    po_id = r.json()["id"]
    assert r.json()["status"] == "PENDING_APPROVAL"

    r = await async_client.post(f"/api/v1/procurement/purchase-orders/{po_id}/transition",
                                json={"to_state": "APPROVED"})
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["error"] == "invalid_transition"


# ── Connector ────────────────────────────────────────────────────────────

def test_connector_rejects_unsupported_provider():
    with pytest.raises(ValueError):
        ProcurementSyncConnector("t1", "sap_mm", {"access_token": "x"})


def test_connector_requires_provider_specific_credentials():
    with pytest.raises(ValueError):
        ProcurementSyncConnector("t1", "coupa", {"access_token": "x"})  # no instance
    with pytest.raises(ValueError):
        ProcurementSyncConnector("t1", "netsuite", {"access_token": "x"})  # no account_id
    with pytest.raises(ValueError):
        ProcurementSyncConnector("t1", "ariba", {"access_token": "x"})  # no realm
    with pytest.raises(ValueError):
        ProcurementSyncConnector("t1", "coupa", {"instance": "acme"})  # no access_token


def test_connector_base_urls_per_provider():
    coupa = ProcurementSyncConnector("t1", "coupa", {"instance": "acme", "access_token": "x"})
    assert coupa.base_url == "https://acme.coupahost.com/api"
    netsuite = ProcurementSyncConnector("t1", "netsuite", {"account_id": "123", "access_token": "x"})
    assert "123.suitetalk.api.netsuite.com" in netsuite.base_url
    ariba = ProcurementSyncConnector("t1", "ariba", {"realm": "acme-realm", "access_token": "x"})
    assert "acme-realm" in ariba.base_url
    assert coupa.headers["Authorization"] == "Bearer x"


# ── Seed idempotency ─────────────────────────────────────────────────────

async def test_seed_is_idempotent():
    from app.core.database import AsyncSessionLocal
    from app.procurement.seed import seed

    await seed()
    await seed()  # a second run must not duplicate rows

    async with AsyncSessionLocal() as db2:
        rows = (await db2.execute(select(VendorContract).where(
            VendorContract.tenant_id == "tenant_acme",
            VendorContract.vendor_name == "Crimson Star Trading Ltd",
        ))).scalars().all()
        assert len(rows) == 1


# ── Sourcing / Spend Guard agent wiring (real gated pipeline, no-provider path) ──

@pytest.mark.asyncio
async def test_assess_requisition_endpoint_routes_through_gated_pipeline(
    async_client: AsyncClient, monkeypatch,
):
    if os.environ.get("KAEOS_FAKE_LLM"):
        pytest.skip("Uses its own no-provider simulation; incompatible with KAEOS_FAKE_LLM")
    monkeypatch.setattr(LLMRouter, "provider_available", _no_provider)
    from app.core.database import init_db
    await init_db()

    r = await async_client.post("/api/v1/procurement/requisitions", json={
        "item_description": "Gated assess test item", "quantity": 3, "unit_price": 12.0,
    })
    assert r.status_code == 201, r.text
    req_id = r.json()["id"]

    r = await async_client.post(f"/api/v1/procurement/requisitions/{req_id}/assess")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("status")  # a real pipeline status, not swallowed


async def test_assess_requisition_404_for_missing(async_client: AsyncClient):
    r = await async_client.post(f"/api/v1/procurement/requisitions/{uuid.uuid4()}/assess")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_guard_purchase_order_endpoint_runs_the_four_gates(
    async_client: AsyncClient, monkeypatch,
):
    if os.environ.get("KAEOS_FAKE_LLM"):
        pytest.skip("Uses its own no-provider simulation; incompatible with KAEOS_FAKE_LLM")
    monkeypatch.setattr(LLMRouter, "provider_available", _no_provider)
    from app.core.database import init_db
    await init_db()

    r = await async_client.post("/api/v1/procurement/purchase-orders", json={
        "vendor_name": "Guard Test Vendor",
        "lines": [{"description": "widgets", "quantity": 10, "unit_price": 999999}],
    })
    assert r.status_code == 201, r.text
    po_id = r.json()["id"]

    r = await async_client.post(f"/api/v1/procurement/purchase-orders/{po_id}/guard", json={})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["po_id"] == po_id
    assert len(body["gates"]) == 4
    codes = {g["code"] for g in body["gates"]}
    assert codes == {"SPEND_AUTHORIZATION", "SEGREGATION_OF_DUTIES", "THREE_WAY_MATCH", "OFAC_SANCTIONS"}
    # A huge, unauthorized, unscreened order cannot be safe to approve.
    assert body["safe_to_approve"] is False
    assert body["blocking_controls"]
    assert "gated" in body and body["gated"].get("status")


async def test_guard_purchase_order_404_for_missing(async_client: AsyncClient):
    r = await async_client.post(f"/api/v1/procurement/purchase-orders/{uuid.uuid4()}/guard", json={})
    assert r.status_code == 404
