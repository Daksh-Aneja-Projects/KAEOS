"""H12: the first three cross-department automations over the event bus.

Departments were islands. With the bus wired (H8), a department event now becomes
governed work elsewhere: HR offboarding -> IT deprovision mission; a lending
adverse-action -> a compliance review signal; a support escalation -> an ops
signal. emit()->handler dispatch is proven in test_event_bus_wiring; here we
exercise the handlers directly (deterministic — no fire-and-forget interleaving
on the shared StaticPool connection)."""
import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.event_mesh import ExternalSignal
from app.models.missions import Mission
from app.services import cross_department as xd

TENANT = "tenant_h12"


@pytest.mark.asyncio
async def test_offboarding_spawns_deprovision_mission():
    await xd._on_employee_offboarded(
        {"tenant_id": TENANT, "payload": {"employee_id": "emp-h12"}})
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(select(Mission).where(
            Mission.tenant_id == TENANT))).scalars().all()
    assert any("Deprovision" in (m.goal or "") for m in rows), \
        "offboarding must spawn a governed IT-deprovision mission"


@pytest.mark.asyncio
async def test_adverse_action_raises_compliance_signal():
    await xd._on_lending_adverse_action(
        {"tenant_id": TENANT, "payload": {"application_number": "APP-h12"}})
    async with AsyncSessionLocal() as db:
        sigs = (await db.execute(select(ExternalSignal).where(
            ExternalSignal.tenant_id == TENANT,
            ExternalSignal.source == "lending"))).scalars().all()
    assert sigs and "Fair-lending" in sigs[0].title


@pytest.mark.asyncio
async def test_support_escalation_raises_ops_signal():
    await xd._on_support_ticket_escalated(
        {"tenant_id": TENANT, "payload": {"ticket_id": "T-h12"}})
    async with AsyncSessionLocal() as db:
        sigs = (await db.execute(select(ExternalSignal).where(
            ExternalSignal.tenant_id == TENANT,
            ExternalSignal.source == "support"))).scalars().all()
    assert sigs, "a support escalation must raise an operations signal"


def test_register_is_idempotent():
    from app.services.event_bus import EventBus, EventType
    xd.register_cross_department_automations()
    xd.register_cross_department_automations()
    assert len(EventBus._handlers.get(EventType.EMPLOYEE_OFFBOARDED.value, [])) == 1
