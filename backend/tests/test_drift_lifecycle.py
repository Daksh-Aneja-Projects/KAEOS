"""H2: drift detection has a status lifecycle and no longer self-silences.

The old job raised one DRIFT ExternalSignal at status NEW and never resolved it;
only mission-linked signals ever reached RESOLVED, so the "one open signal per
tenant" guard suppressed drift forever after the first detection. The job now
resolves the open signal when drift clears and re-raises when it returns.

Runs the real job against the app engine (MaintenanceSessionLocal == the sidecar
engine in tests), with leadership forced on."""
import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.actuation import SorObject
from app.models.event_mesh import ExternalSignal
from app.services import scheduler
from app.services.actuation import Actuator

TENANT = "tenant_drift_lifecycle"


async def _drift_signals():
    async with AsyncSessionLocal() as s:
        return (await s.execute(
            select(ExternalSignal).where(
                ExternalSignal.tenant_id == TENANT,
                ExternalSignal.kind == "DRIFT",
            ).order_by(ExternalSignal.created_at)
        )).scalars().all()


@pytest.mark.asyncio
async def test_drift_signal_resolves_when_clear_and_reraises(monkeypatch):
    monkeypatch.setattr(scheduler, "_is_leader", lambda: True)

    # 1) An untracked SoR row (a write outside the actuation path) = drift.
    async with AsyncSessionLocal() as s:
        s.add(SorObject(tenant_id=TENANT, system="dynamics", object_type="account",
                        external_id="A-1", state={"tier": "gold"}, version=1, deleted=0))
        await s.commit()

    await scheduler.run_drift_detection_job()
    sigs = await _drift_signals()
    assert len(sigs) == 1 and sigs[0].status == "NEW", "first drift raises one open signal"

    # 2) Drift clears — the operator reconciles via a governed action (the row
    # stays; it is now governed, not drifting). The open signal must RESOLVE;
    # the bug was that it never did, so the guard suppressed all future drift.
    async with AsyncSessionLocal() as s:
        await Actuator.apply_action(
            s, tenant_id=TENANT, system="dynamics", object_type="account",
            external_id="A-1", operation="UPDATE", payload={"tier": "gold"},
            actor="operator")
        await s.commit()

    await scheduler.run_drift_detection_job()
    sigs = await _drift_signals()
    assert len(sigs) == 1 and sigs[0].status == "RESOLVED", "cleared drift resolves the signal"

    # 3) New drift appears — a fresh signal must be raised, proving drift is not
    # silenced forever after the first detection.
    async with AsyncSessionLocal() as s:
        s.add(SorObject(tenant_id=TENANT, system="dynamics", object_type="account",
                        external_id="A-2", state={"tier": "silver"}, version=1, deleted=0))
        await s.commit()

    await scheduler.run_drift_detection_job()
    sigs = await _drift_signals()
    assert len(sigs) == 2, "new drift re-raises after an earlier one resolved"
    assert sigs[-1].status == "NEW"
