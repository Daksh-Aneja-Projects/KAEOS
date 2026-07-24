"""v3 Phase 1 — System-of-Record actuation.

A governed write applies to a real backing SoR row, is idempotent on retry,
carries a compensator, and can be reversed to the exact prior state. Drift
(a change made outside the actuation path) is detected.
"""
import pytest
from sqlalchemy import select

from app.models.actuation import SorObject, ActionRecord
from app.services.actuation import Actuator, ActuationError

pytestmark = pytest.mark.asyncio


async def test_create_then_idempotent_retry(db):
    t = "tenant_act"
    r1 = await Actuator.apply_action(
        db, tenant_id=t, system="netsuite", object_type="invoice",
        external_id="INV-1", operation="CREATE", payload={"amount": 100, "status": "open"})
    assert r1.status == "APPLIED"
    assert r1.after_state == {"amount": 100, "status": "open"}

    # Same request again -> same record, no duplicate write.
    r2 = await Actuator.apply_action(
        db, tenant_id=t, system="netsuite", object_type="invoice",
        external_id="INV-1", operation="CREATE", payload={"amount": 100, "status": "open"})
    assert r2.id == r1.id

    objs = (await db.execute(select(SorObject).where(SorObject.tenant_id == t))).scalars().all()
    assert len(objs) == 1
    actions = (await db.execute(select(ActionRecord).where(ActionRecord.tenant_id == t))).scalars().all()
    assert len(actions) == 1


async def test_update_then_reverse_restores_prior_state(db):
    t = "tenant_act2"
    await Actuator.apply_action(
        db, tenant_id=t, system="workday", object_type="employee",
        external_id="E-9", operation="CREATE", payload={"title": "Analyst", "level": 3})
    upd = await Actuator.apply_action(
        db, tenant_id=t, system="workday", object_type="employee",
        external_id="E-9", operation="UPDATE", payload={"level": 5})

    obj = (await db.execute(select(SorObject).where(
        SorObject.tenant_id == t, SorObject.external_id == "E-9"))).scalar_one()
    assert obj.state == {"title": "Analyst", "level": 5}
    assert upd.compensator == {"operation": "UPDATE", "payload": {"title": "Analyst", "level": 3}}

    reversed_rec = await Actuator.reverse_action(db, tenant_id=t, action_id=upd.id)
    assert reversed_rec.status == "REVERSED"

    obj = (await db.execute(select(SorObject).where(
        SorObject.tenant_id == t, SorObject.external_id == "E-9"))).scalar_one()
    assert obj.state == {"title": "Analyst", "level": 3}  # restored


async def test_delete_reverse_recreates(db):
    t = "tenant_act3"
    await Actuator.apply_action(
        db, tenant_id=t, system="sfdc", object_type="opportunity",
        external_id="O-1", operation="CREATE", payload={"stage": "won", "value": 50000})
    dele = await Actuator.apply_action(
        db, tenant_id=t, system="sfdc", object_type="opportunity",
        external_id="O-1", operation="DELETE")
    obj = (await db.execute(select(SorObject).where(
        SorObject.tenant_id == t, SorObject.external_id == "O-1"))).scalar_one()
    assert obj.deleted

    await Actuator.reverse_action(db, tenant_id=t, action_id=dele.id)
    obj = (await db.execute(select(SorObject).where(
        SorObject.tenant_id == t, SorObject.external_id == "O-1"))).scalar_one()
    assert not obj.deleted
    assert obj.state == {"stage": "won", "value": 50000}


async def test_invalid_operation_rejected(db):
    with pytest.raises(ActuationError):
        await Actuator.apply_action(
            db, tenant_id="t", system="x", object_type="y",
            external_id="z", operation="FROB", payload={})


async def test_update_missing_object_rejected(db):
    with pytest.raises(ActuationError):
        await Actuator.apply_action(
            db, tenant_id="t4", system="x", object_type="y",
            external_id="ghost", operation="UPDATE", payload={"a": 1})


async def test_drift_detects_untracked_write(db):
    t = "tenant_act5"
    # A record that appeared in the SoR with no governing action (external write).
    db.add(SorObject(tenant_id=t, system="dynamics", object_type="account",
                     external_id="A-1", state={"tier": "gold"}, version=1, deleted=0))
    await db.commit()

    report = await Actuator.compute_drift(db, tenant_id=t)
    assert report["drift_count"] == 1
    assert report["drift"][0]["external_id"] == "A-1"
    assert report["drift"][0]["reason"] == "untracked_write"

    # A governed create is in sync (no drift).
    await Actuator.apply_action(
        db, tenant_id=t, system="dynamics", object_type="account",
        external_id="A-2", operation="CREATE", payload={"tier": "silver"})
    report2 = await Actuator.compute_drift(db, tenant_id=t)
    assert any(d["external_id"] == "A-1" for d in report2["drift"])
    assert all(d["external_id"] != "A-2" for d in report2["drift"])


async def test_reversal_is_not_drift(db):
    """A reversal is itself a governed modification and must not read as drift."""
    t = "tenant_act6"
    await Actuator.apply_action(
        db, tenant_id=t, system="sfdc", object_type="lead",
        external_id="L-1", operation="CREATE", payload={"score": 10})
    upd = await Actuator.apply_action(
        db, tenant_id=t, system="sfdc", object_type="lead",
        external_id="L-1", operation="UPDATE", payload={"score": 90})
    assert (await Actuator.compute_drift(db, tenant_id=t))["drift_count"] == 0

    await Actuator.reverse_action(db, tenant_id=t, action_id=upd.id)
    report = await Actuator.compute_drift(db, tenant_id=t)
    assert report["drift_count"] == 0  # reversal is governed, not drift
