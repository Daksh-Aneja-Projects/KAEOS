"""Outbound write-back queue is idempotent: queueing the same
(tenant_id, idempotency_key) twice must yield ONE row / the same id, so a
retried governed action does not double-send or double-meter.

Fail-closed guard: if the dedup short-circuit in queue_outbound is removed,
the second call inserts a second row and this test fails.
"""
import pytest
from sqlalchemy import func, select

from app.services.sync_engine import queue_outbound

TENANT = "tenant_idem_test"
KEY = "act-idem-key-123"


@pytest.fixture(autouse=True)
async def _tables():
    from app.core.database import engine as app_engine
    from app.models.sync import OutboundWrite
    from sqlalchemy import text
    async with app_engine.begin() as conn:
        await conn.run_sync(OutboundWrite.__table__.create, checkfirst=True)
        await conn.execute(text("DELETE FROM outbound_writes WHERE tenant_id = :t"),
                           {"t": TENANT})
    yield


@pytest.mark.asyncio
async def test_same_idempotency_key_queues_once():
    id1 = await queue_outbound(TENANT, "employee", "emp-1", "upsert",
                               {"x": 1}, idempotency_key=KEY)
    id2 = await queue_outbound(TENANT, "employee", "emp-1", "upsert",
                               {"x": 2}, idempotency_key=KEY)
    assert id1 and id2 and id1 == id2

    from app.core.database import AsyncSessionLocal
    from app.models.sync import OutboundWrite
    async with AsyncSessionLocal() as db:
        n = (await db.execute(
            select(func.count()).select_from(OutboundWrite)
            .where(OutboundWrite.tenant_id == TENANT,
                   OutboundWrite.idempotency_key == KEY)
        )).scalar_one()
    assert n == 1


@pytest.mark.asyncio
async def test_no_key_does_not_dedup():
    """Absent a caller key, each queue is a distinct write (default = fresh uuid)."""
    a = await queue_outbound(TENANT, "employee", "emp-2", "upsert", {})
    b = await queue_outbound(TENANT, "employee", "emp-2", "upsert", {})
    assert a and b and a != b
