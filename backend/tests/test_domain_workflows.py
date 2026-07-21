"""
Domain workflow engine tests: guarded transitions, tenant isolation,
side-effect hooks and the transition audit trail — exercised over the real
HTTP endpoints for several domains.
"""
from datetime import date

import pytest
from httpx import AsyncClient

TENANT = "tenant_acme"  # dev-context tenant resolved for unauthenticated tests


async def _seed_ticket(db, tenant_id=TENANT, status="NEW"):
    from app.support.models.tickets import Ticket, TicketStatus
    t = Ticket(
        tenant_id=tenant_id,
        ticket_number=f"T-{tenant_id[-4:]}-{status}",
        subject="Printer on fire",
        description="It is very much on fire.",
        status=TicketStatus(status),
    )
    db.add(t)
    await db.commit()
    await db.refresh(t)
    return t


@pytest.mark.asyncio
async def test_ticket_valid_transition_stamps_sla_fields(async_client: AsyncClient, db):
    t = await _seed_ticket(db)

    r = await async_client.post(f"/api/v1/support/tickets/{t.id}/transition",
                                json={"to_state": "ASSIGNED"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["from_state"] == "NEW"
    assert body["to_state"] == "ASSIGNED"
    assert "RESOLVED" in body["allowed_next"]

    r = await async_client.post(f"/api/v1/support/tickets/{t.id}/transition",
                                json={"to_state": "RESOLVED", "note": "extinguished"})
    assert r.status_code == 200, r.text

    await db.refresh(t)
    assert t.first_response_at is not None  # stamped on ASSIGNED
    assert t.resolved_at is not None        # stamped on RESOLVED


@pytest.mark.asyncio
async def test_ticket_invalid_transition_is_409_with_allowed_list(async_client: AsyncClient, db):
    t = await _seed_ticket(db, status="NEW")
    r = await async_client.post(f"/api/v1/support/tickets/{t.id}/transition",
                                json={"to_state": "RESOLVED"})
    assert r.status_code == 409, r.text
    detail = r.json()["detail"]
    assert detail["error"] == "invalid_transition"
    assert detail["from_state"] == "NEW"
    assert set(detail["allowed"]) == {"ASSIGNED", "OPEN", "CLOSED"}


@pytest.mark.asyncio
async def test_unknown_state_is_422(async_client: AsyncClient, db):
    t = await _seed_ticket(db)
    r = await async_client.post(f"/api/v1/support/tickets/{t.id}/transition",
                                json={"to_state": "TELEPORTED"})
    assert r.status_code == 422, r.text


@pytest.mark.asyncio
async def test_cross_tenant_row_is_404(async_client: AsyncClient, db):
    t = await _seed_ticket(db, tenant_id="tenant_other")
    r = await async_client.post(f"/api/v1/support/tickets/{t.id}/transition",
                                json={"to_state": "ASSIGNED"})
    # 404, not 403: a 403 would confirm the foreign id exists.
    assert r.status_code == 404, r.text


@pytest.mark.asyncio
async def test_workflow_events_trail_is_recorded(async_client: AsyncClient, db):
    t = await _seed_ticket(db)
    await async_client.post(f"/api/v1/support/tickets/{t.id}/transition",
                            json={"to_state": "OPEN"})
    r = await async_client.get(f"/api/v1/support/workflow-events?entity_id={t.id}")
    assert r.status_code == 200
    events = r.json()
    assert len(events) == 1
    assert events[0]["from_state"] == "NEW"
    assert events[0]["to_state"] == "OPEN"
    assert events[0]["domain"] == "support"


@pytest.mark.asyncio
async def test_workflows_spec_endpoint_shape(async_client: AsyncClient):
    r = await async_client.get("/api/v1/support/workflows")
    assert r.status_code == 200
    spec = r.json()["ticket"]
    assert spec["status_attr"] == "status"
    assert spec["transitions"]["NEW"] == ["ASSIGNED", "OPEN", "CLOSED"]


@pytest.mark.asyncio
async def test_invoice_paid_hook_zeroes_balance(async_client: AsyncClient, db):
    from app.finance.models.accounts_payable import Invoice, InvoiceStatus, Vendor, VendorStatus
    v = Vendor(tenant_id=TENANT, vendor_code="V-1", name="Acme Paper",
               status=VendorStatus.ACTIVE)
    db.add(v)
    await db.commit()
    inv = Invoice(
        tenant_id=TENANT, vendor_id=v.id, invoice_number="INV-100",
        invoice_date=date(2026, 7, 1), due_date=date(2026, 8, 1),
        status=InvoiceStatus.APPROVED,
        subtotal=100, total_amount=110, balance_due=110,
    )
    db.add(inv)
    await db.commit()
    await db.refresh(inv)

    r = await async_client.post(f"/api/v1/finance/invoices/{inv.id}/transition",
                                json={"to_state": "PAID"})
    assert r.status_code == 200, r.text
    await db.refresh(inv)
    assert float(inv.balance_due) == 0
    assert float(inv.amount_paid) == 110


@pytest.mark.asyncio
async def test_opportunity_won_sets_probability(async_client: AsyncClient, db):
    from app.sales.models.pipeline import Opportunity, OpportunityStage
    opp = Opportunity(tenant_id=TENANT, name="Mega Deal",
                      stage=OpportunityStage.NEGOTIATION, amount=50000, probability=60)
    db.add(opp)
    await db.commit()
    await db.refresh(opp)

    # Skipping stages is rejected...
    r = await async_client.post(f"/api/v1/sales/opportunities/{opp.id}/transition",
                                json={"to_state": "PROSPECTING"})
    assert r.status_code == 409

    # ...closing won from negotiation is allowed and sets probability to 100.
    r = await async_client.post(f"/api/v1/sales/opportunities/{opp.id}/transition",
                                json={"to_state": "CLOSED_WON"})
    assert r.status_code == 200, r.text
    await db.refresh(opp)
    assert opp.probability == 100.0


@pytest.mark.asyncio
async def test_incident_resolution_stamps_mttr(async_client: AsyncClient, db):
    from app.engineering.models.incidents import Incident, IncidentStatus
    inc = Incident(tenant_id=TENANT, incident_number="INC-9",
                   title="API latency spike", status=IncidentStatus.DETECTED)
    db.add(inc)
    await db.commit()
    await db.refresh(inc)

    for state in ["TRIAGED", "MITIGATING", "RESOLVED"]:
        r = await async_client.post(f"/api/v1/engineering/incidents/{inc.id}/transition",
                                    json={"to_state": state})
        assert r.status_code == 200, r.text

    await db.refresh(inc)
    assert inc.acknowledged_at is not None
    assert inc.resolved_at is not None
    assert inc.time_to_resolve_mins is not None


@pytest.mark.asyncio
async def test_contract_activation_stamps_effective_date(async_client: AsyncClient, db):
    from app.legal.models.contracts import Contract, ContractStatus
    c = Contract(tenant_id=TENANT, title="MSA - Globex", counterparty="Globex",
                 contract_type="MSA", status=ContractStatus.SIGNED)
    db.add(c)
    await db.commit()
    await db.refresh(c)

    r = await async_client.post(f"/api/v1/legal/contracts/{c.id}/transition",
                                json={"to_state": "ACTIVE"})
    assert r.status_code == 200, r.text
    await db.refresh(c)
    assert c.effective_date is not None
