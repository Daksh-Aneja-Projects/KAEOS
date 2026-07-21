"""
Domain analytics endpoint tests: every domain returns the shared shape
(kpis / charts / insights), values are computed from real rows, and foreign
tenants never leak into the aggregates.
"""
import pytest
from httpx import AsyncClient

TENANT = "tenant_acme"

DOMAINS = ["finance", "hr", "sales", "support", "operations", "legal", "engineering"]


@pytest.mark.asyncio
@pytest.mark.parametrize("domain", DOMAINS)
async def test_analytics_shape_on_empty_tenant(async_client: AsyncClient, domain):
    r = await async_client.get(f"/api/v1/{domain}/analytics")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["domain"] == domain
    assert isinstance(body["kpis"], list) and body["kpis"]
    assert isinstance(body["charts"], list) and body["charts"]
    assert isinstance(body["insights"], list) and body["insights"]
    for kpi in body["kpis"]:
        assert {"key", "label", "value", "format"} <= set(kpi)
    for chart in body["charts"]:
        assert {"key", "title", "type", "items"} <= set(chart)


@pytest.mark.asyncio
async def test_support_analytics_counts_only_this_tenant(async_client: AsyncClient, db):
    from app.support.models.tickets import Ticket, TicketStatus
    db.add(Ticket(tenant_id=TENANT, ticket_number="T-A1", subject="a",
                  description="d", status=TicketStatus.OPEN))
    db.add(Ticket(tenant_id="tenant_other", ticket_number="T-B1", subject="b",
                  description="d", status=TicketStatus.OPEN))
    await db.commit()

    r = await async_client.get("/api/v1/support/analytics")
    assert r.status_code == 200
    kpis = {k["key"]: k["value"] for k in r.json()["kpis"]}
    assert kpis["backlog"] == 1
    assert kpis["total"] == 1


@pytest.mark.asyncio
async def test_sales_analytics_computes_win_rate(async_client: AsyncClient, db):
    from app.sales.models.pipeline import Opportunity, OpportunityStage
    for stage, amount in [(OpportunityStage.CLOSED_WON, 1000),
                          (OpportunityStage.CLOSED_WON, 3000),
                          (OpportunityStage.CLOSED_LOST, 500),
                          (OpportunityStage.NEGOTIATION, 800)]:
        db.add(Opportunity(tenant_id=TENANT, name=f"d-{stage.value}-{amount}",
                           stage=stage, amount=amount, probability=50))
    await db.commit()

    r = await async_client.get("/api/v1/sales/analytics")
    assert r.status_code == 200
    kpis = {k["key"]: k["value"] for k in r.json()["kpis"]}
    assert kpis["win_rate"] == pytest.approx(66.666, rel=1e-2)
    assert kpis["open_deals"] == 1
    assert kpis["pipeline"] == 800.0
    assert kpis["weighted"] == pytest.approx(400.0)
