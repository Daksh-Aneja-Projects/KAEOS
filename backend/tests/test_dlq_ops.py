"""DLQ operations: operator requeue of dead-lettered outbound writes plus the
status filter/counts on the outbound queue listing.

Unlike test_writeback_reliability.py (which drives the sync engine on the app
engine), these endpoints go through the overridden get_db, so rows are seeded
on the test engine via the ``db`` fixture and read back the same way.
"""
import pytest
from httpx import AsyncClient
from sqlalchemy import select

TENANT = "tenant_dlq_test"
OTHER = "tenant_dlq_other"
HDR = {"X-Tenant-ID": TENANT}


def _write(status="DEAD", tenant_id=TENANT, **kw):
    from app.models.sync import OutboundWrite
    defaults = dict(tenant_id=tenant_id, entity_type="employee", internal_id="e1",
                    op="UPSERT", payload={"x": 1}, status=status, attempts=5,
                    last_error="DEAD after 5 attempts: boom")
    defaults.update(kw)
    return OutboundWrite(**defaults)


@pytest.mark.asyncio
async def test_requeue_resets_dead_row_and_preserves_idempotency_key(
        async_client: AsyncClient, db):
    from app.models.sync import OutboundWrite
    w = _write(status="DEAD", idempotency_key="stable-token-42")
    db.add(w)
    await db.commit()

    r = await async_client.post(
        f"/api/v1/integrations/sync/outbound/{w.id}/requeue", headers=HDR)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "PENDING" and body["attempts"] == 0
    # CRITICAL: the SoR-side dedup token must survive the replay.
    assert body["idempotency_key"] == "stable-token-42"

    row = (await db.execute(select(OutboundWrite).where(
        OutboundWrite.id == w.id))).scalar_one()
    await db.refresh(row)
    assert row.status == "PENDING"
    assert row.attempts == 0
    assert row.last_error is None
    assert row.idempotency_key == "stable-token-42"


@pytest.mark.asyncio
async def test_requeue_rejects_non_terminal_status(async_client: AsyncClient, db):
    w = _write(status="PENDING", attempts=0, last_error=None)
    db.add(w)
    await db.commit()
    r = await async_client.post(
        f"/api/v1/integrations/sync/outbound/{w.id}/requeue", headers=HDR)
    assert r.status_code == 400
    assert "PENDING" in r.json()["detail"]


@pytest.mark.asyncio
async def test_requeue_cross_tenant_is_404(async_client: AsyncClient, db):
    w = _write(status="DEAD", tenant_id=OTHER)
    db.add(w)
    await db.commit()
    r = await async_client.post(
        f"/api/v1/integrations/sync/outbound/{w.id}/requeue", headers=HDR)
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_outbound_status_filter_and_counts(async_client: AsyncClient, db):
    db.add(_write(status="DEAD", internal_id="d1"))
    db.add(_write(status="DEAD", internal_id="d2"))
    db.add(_write(status="SENT", internal_id="s1", attempts=1, last_error=None))
    db.add(_write(status="PENDING", internal_id="p1", attempts=0, last_error=None))
    # Another tenant's row must appear in neither the list nor the counts.
    db.add(_write(status="DEAD", tenant_id=OTHER, internal_id="x1"))
    await db.commit()

    r = await async_client.get(
        "/api/v1/integrations/sync/outbound?status=DEAD", headers=HDR)
    assert r.status_code == 200, r.text
    body = r.json()
    assert {row["internal_id"] for row in body["outbound"]} == {"d1", "d2"}
    assert all(row["status"] == "DEAD" for row in body["outbound"])
    # Counts are tenant-wide per status, independent of the filter.
    assert body["counts"] == {"DEAD": 2, "SENT": 1, "PENDING": 1}

    # Unknown status is rejected by validation, not silently ignored.
    r = await async_client.get(
        "/api/v1/integrations/sync/outbound?status=BOGUS", headers=HDR)
    assert r.status_code == 422


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
