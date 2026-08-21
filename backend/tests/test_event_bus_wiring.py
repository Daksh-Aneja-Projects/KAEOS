"""H8: the internal event bus is wired — emit() persists a SystemEvent, fans out
to registered in-process handlers, and the three lifecycle chokepoints (mission
terminal, HITL decision, actuation applied) actually call it.

emit() writes through the app's own AsyncSessionLocal (the sidecar engine in the
test harness), so rows are read back through that same session, never the `db`
fixture's test engine (see tests/conftest.py — two engines, both schema'd)."""
import asyncio

import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.events import SystemEvent
from app.services.event_bus import EventBus, EventType, event_bus

TENANT = "tenant_eventbus_test"


async def _events(tenant=TENANT):
    async with AsyncSessionLocal() as s:
        return (await s.execute(
            select(SystemEvent).where(SystemEvent.tenant_id == tenant)
        )).scalars().all()


@pytest.mark.asyncio
async def test_emit_persists_and_fans_out_to_internal_handlers():
    seen = []

    async def _handler(event_data):
        seen.append(event_data)

    EventBus.on(EventType.PROCESS_COMPLETED, _handler)
    # on() is idempotent — registering the same handler twice must not double-fire.
    EventBus.on(EventType.PROCESS_COMPLETED, _handler)
    try:
        res = await event_bus.emit(
            EventType.PROCESS_COMPLETED,
            {"mission_id": "m1", "status": "COMPLETED"},
            tenant_id=TENANT,
        )
        assert res["status"] == "persisted"

        rows = await _events()
        assert len(rows) == 1
        assert rows[0].event_type == "process.completed"
        assert rows[0].payload["mission_id"] == "m1"

        # Handlers are fire-and-forget tasks; yield the loop so they run.
        await asyncio.sleep(0.05)
        assert len(seen) == 1, "idempotent registration must not double-fire"
        assert seen[0]["type"] == "process.completed"
    finally:
        EventBus._handlers.get(EventType.PROCESS_COMPLETED.value, []).clear()


@pytest.mark.asyncio
async def test_a_failing_handler_never_blocks_persistence():
    async def _boom(event_data):
        raise RuntimeError("handler exploded")

    EventBus.on(EventType.HITL_APPROVED, _boom)
    try:
        await event_bus.emit(
            EventType.HITL_APPROVED, {"execution_id": "x"}, tenant_id=TENANT)
        await asyncio.sleep(0.05)
        # The event is still persisted despite the handler raising.
        rows = await _events()
        assert len(rows) == 1
        assert rows[0].event_type == "hitl.approved"
    finally:
        EventBus._handlers.get(EventType.HITL_APPROVED.value, []).clear()


@pytest.mark.asyncio
async def test_actuation_apply_emits_system_event(db):
    """A governed write through the Actuator lands an actuation.applied event —
    proving the chokepoint calls the bus, not just that the bus works."""
    from app.services.actuation.actuator import Actuator

    async with AsyncSessionLocal() as s:
        await Actuator.apply_action(
            s, tenant_id=TENANT, system="workday", object_type="employee",
            external_id="E-100", operation="CREATE", payload={"name": "A"},
            actor="tester",
        )
    await asyncio.sleep(0.02)
    rows = await _events()
    assert any(r.event_type == "actuation.applied" for r in rows), \
        "apply_action must publish actuation.applied onto the bus"
