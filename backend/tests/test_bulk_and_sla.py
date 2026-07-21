"""
Sprint-3 backend tests: bulk transitions (per-id outcomes, dedupe, tenant
isolation) and the SLA/stale-state sweep (find_stale_entities + /org/stale +
health-denting pulse insights).
"""
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient

TENANT = "tenant_acme"


async def _seed_tickets(db, n=3, status="NEW", tenant_id=TENANT, aged_hours=0):
    import uuid
    from app.support.models.tickets import Ticket, TicketStatus
    rows = []
    for i in range(n):
        t = Ticket(tenant_id=tenant_id, ticket_number=f"T-{uuid.uuid4().hex[:10]}",
                   subject=f"bulk {i}", description="d", status=TicketStatus(status))
        db.add(t)
        rows.append(t)
    await db.commit()
    for t in rows:
        await db.refresh(t)
    if aged_hours:
        # Backdate updated_at directly — SQLAlchemy onupdate would overwrite it
        # on the next flush, so this is set last.
        from sqlalchemy import update
        from app.support.models.tickets import Ticket as T
        stamp = datetime.now(timezone.utc) - timedelta(hours=aged_hours)
        await db.execute(update(T).where(T.id.in_([t.id for t in rows]))
                         .values(updated_at=stamp, created_at=stamp))
        await db.commit()
    return rows


@pytest.mark.asyncio
async def test_bulk_transition_mixed_outcomes(async_client: AsyncClient, db):
    ok_rows = await _seed_tickets(db, n=2, status="NEW")
    bad_rows = await _seed_tickets(db, n=1, status="RESOLVED")   # NEW->OPEN illegal from RESOLVED? RESOLVED->OPEN is legal; use CLOSED
    foreign = await _seed_tickets(db, n=1, tenant_id="tenant_other")

    ids = [r.id for r in ok_rows] + [bad_rows[0].id, foreign[0].id, ok_rows[0].id]  # dup of first
    r = await async_client.post("/api/v1/support/workflows/ticket/bulk-transition",
                                json={"ids": ids, "to_state": "ASSIGNED"})
    assert r.status_code == 200, r.text
    body = r.json()
    # Dedupe: 4 unique ids processed, not 5.
    assert body["requested"] == 4
    assert body["succeeded"] == 2            # the two NEW tickets
    by_id = {x["id"]: x for x in body["results"]}
    assert by_id[bad_rows[0].id]["ok"] is False        # RESOLVED can't go ASSIGNED
    assert by_id[bad_rows[0].id]["status_code"] == 409
    assert by_id[foreign[0].id]["ok"] is False         # cross-tenant → 404
    assert by_id[foreign[0].id]["status_code"] == 404


@pytest.mark.asyncio
async def test_bulk_transition_unknown_entity_404(async_client: AsyncClient):
    r = await async_client.post("/api/v1/support/workflows/unicorn/bulk-transition",
                                json={"ids": ["x"], "to_state": "OPEN"})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_find_stale_entities_flags_only_breaches(db):
    from app.core.workflow import find_stale_entities
    from app.support.services.workflows import TICKET_WORKFLOW

    await _seed_tickets(db, n=2, status="NEW", aged_hours=10)   # NEW SLA is 4h → stale
    await _seed_tickets(db, n=1, status="NEW", aged_hours=1)    # fresh
    await _seed_tickets(db, n=1, status="NEW", aged_hours=99,
                        tenant_id="tenant_other")               # foreign tenant

    breaches = await find_stale_entities(db, TICKET_WORKFLOW, TENANT)
    assert len(breaches) == 2
    assert all(b["state"] == "NEW" and b["over_by_hours"] > 5 for b in breaches)
    # Worst-first ordering.
    assert breaches[0]["over_by_hours"] >= breaches[-1]["over_by_hours"]


@pytest.mark.asyncio
async def test_org_stale_endpoint(async_client: AsyncClient, db):
    await _seed_tickets(db, n=1, status="ASSIGNED", aged_hours=48)  # ASSIGNED SLA 24h
    r = await async_client.get("/api/v1/org/stale")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] >= 1
    assert any(b["entity_type"] == "ticket" and b["state"] == "ASSIGNED"
               for b in body["breaches"])

    # Domain filter excludes other domains.
    r = await async_client.get("/api/v1/org/stale?domain=legal")
    assert all(b["domain"] == "legal" for b in r.json()["breaches"])


@pytest.mark.asyncio
async def test_pulse_health_dented_by_sla_breaches(async_client: AsyncClient, db):
    r0 = await async_client.get("/api/v1/org/pulse")
    support0 = next(d for d in r0.json()["domains"] if d["domain"] == "support")

    await _seed_tickets(db, n=3, status="NEW", aged_hours=20)
    r1 = await async_client.get("/api/v1/org/pulse")
    body = r1.json()
    support1 = next(d for d in body["domains"] if d["domain"] == "support")
    assert support1["sla_breaches"] == 3
    assert support1["health"] < support0["health"]
    assert any("past their state SLA" in i["message"] and i["domain"] == "support"
               for i in body["insights"])
