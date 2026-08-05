"""Closed loops L3 (drift -> reconcile/auto-heal) and L5-reverse (autonomy governor)."""
import uuid


from app.services.actuation import Actuator
from app.services.autonomy_governor import run_autonomy_governor
from app.models.domain import Skill, SkillExecution
from app.models.settings import AutonomyPolicy


T = "tenant_l3l5"


# ── L3: reconcile re-asserts the last governed state ──────────────────────────

async def test_reconcile_reasserts_last_governed_state(db):
    # Apply a governed action, then simulate an out-of-band change to the SoR.
    await Actuator.apply_action(
        db, tenant_id=T, system="sandbox", object_type="record", external_id="r1",
        operation="CREATE", payload={"status": "approved"}, actor="agent",
    )
    from app.models.actuation import SorObject
    from sqlalchemy import select
    obj = (await db.execute(select(SorObject).where(
        SorObject.tenant_id == T, SorObject.external_id == "r1"))).scalar_one()
    obj.state = {"status": "tampered"}          # untracked write
    await db.commit()

    res = await Actuator.reconcile_object(
        db, tenant_id=T, system="sandbox", object_type="record", external_id="r1")
    assert res["status"] == "RECONCILED"

    obj2 = (await db.execute(select(SorObject).where(
        SorObject.tenant_id == T, SorObject.external_id == "r1"))).scalar_one()
    assert obj2.state == {"status": "approved"}  # healed back to the governed state


async def test_reconcile_without_baseline_is_noop(db):
    res = await Actuator.reconcile_object(
        db, tenant_id=T, system="sandbox", object_type="record", external_id="never")
    assert res["status"] == "no_governed_baseline"


# ── L5-reverse: the governor nudges dials from measured outcomes ──────────────

async def _seed_execs(db, department, n, *, safe, overridden=0, failed=0):
    db.add(Skill(id=str(uuid.uuid4()), skill_id=f"{department}_skill", tenant_id=T,
                 department=department, status="ACTIVE", confidence=0.8))
    from datetime import datetime, timezone
    for i in range(n):
        if i < safe:
            status, hitl = "SUCCESS_CLEAN", False
        elif i < safe + overridden:
            status, hitl = "HUMAN_OVERRIDDEN", False
        elif i < safe + overridden + failed:
            status, hitl = "FAILED_RULE", False
        else:
            status, hitl = "SUCCESS_CLEAN", True   # routed to human (not autonomous-safe)
        db.add(SkillExecution(id=str(uuid.uuid4()), tenant_id=T, skill_id_name=f"{department}_skill",
                              status=status, hitl_required=hitl,
                              started_at=datetime.now(timezone.utc)))
    await db.commit()


async def test_governor_relaxes_dial_when_autonomy_is_high_and_clean(db):
    # 30 executions, all autonomous + clean -> rate 1.0, fallout 0 -> relax.
    await _seed_execs(db, "operations", 30, safe=30)
    receipt = await run_autonomy_governor(db, T)
    assert receipt["adjusted"] == 1
    from sqlalchemy import select
    pol = (await db.execute(select(AutonomyPolicy).where(
        AutonomyPolicy.tenant_id == T, AutonomyPolicy.domain == "operations"))).scalar_one()
    assert pol.auto_managed is True
    assert pol.min_confidence < 0.82           # relaxed below the platform default


async def test_governor_tightens_dial_on_high_fallout(db):
    # 30 execs: 15 safe, 10 overridden, 5 failed -> bad_fraction 0.5 -> tighten.
    await _seed_execs(db, "finance", 30, safe=15, overridden=10, failed=5)
    receipt = await run_autonomy_governor(db, T)
    assert receipt["adjusted"] == 1
    from sqlalchemy import select
    pol = (await db.execute(select(AutonomyPolicy).where(
        AutonomyPolicy.tenant_id == T, AutonomyPolicy.domain == "finance"))).scalar_one()
    assert pol.min_confidence > 0.82           # tightened above the default


async def test_governor_never_overrides_human_set_dial(db):
    db.add(AutonomyPolicy(tenant_id=T, domain="legal", min_confidence=0.7, auto_managed=False))
    await _seed_execs(db, "legal", 30, safe=30)   # would otherwise relax
    await db.commit()
    await run_autonomy_governor(db, T)
    from sqlalchemy import select
    pol = (await db.execute(select(AutonomyPolicy).where(
        AutonomyPolicy.tenant_id == T, AutonomyPolicy.domain == "legal"))).scalar_one()
    assert pol.min_confidence == 0.7            # untouched (human override wins)


async def test_governor_ignores_thin_evidence(db):
    await _seed_execs(db, "sales", 5, safe=5)     # below the sample floor
    receipt = await run_autonomy_governor(db, T)
    assert receipt["adjusted"] == 0


def _capture_audit(monkeypatch):
    """Spy on the audit call. record_security_event opens its own session and
    swallows its own failures, so asserting through the DB would test that
    plumbing rather than the governor's decision to record."""
    seen = []

    async def _spy(**kw):
        seen.append(kw)

    monkeypatch.setattr("app.services.autonomy_governor.record_security_event", _spy)
    return seen


async def test_governor_audits_every_dial_change(db, monkeypatch):
    """The machine widening its own authority must leave a record.

    A human moving the dial writes a CONFIG_CHANGE row; the governor did not, so
    the only actor that can grant itself more autonomy was the only one doing it
    silently. The record carries the evidence that justified the move, not just
    the new value, or it cannot be challenged after the fact.
    """
    seen = _capture_audit(monkeypatch)
    await _seed_execs(db, "legal", 30, safe=30)   # clean -> governor relaxes
    receipt = await run_autonomy_governor(db, T)
    assert receipt["adjusted"] == 1

    legal = [e for e in seen if e.get("resource_id") == "legal"]
    assert len(legal) == 1, "a machine dial change must be audited exactly once"

    e = legal[0]
    assert e["event_type"] == "CONFIG_CHANGE"
    assert e["actor"] == "autonomy-governor"      # attributable to the machine
    assert e["actor_role"] == "system"
    assert e["resource_type"] == "autonomy_policy"
    d = e["details"]
    assert d["direction"] == "relaxed"
    assert d["previous_min_confidence"] > d["min_confidence"]
    assert d["safe_autonomy_rate"] == 1.0
    assert d["samples"] == 30
    assert "legal" in d["reason"]


async def test_governor_audits_a_tightening_with_its_evidence(db, monkeypatch):
    seen = _capture_audit(monkeypatch)
    await _seed_execs(db, "finance", 30, safe=15, overridden=10, failed=5)
    await run_autonomy_governor(db, T)

    e = [x for x in seen if x.get("resource_id") == "finance"][0]
    d = e["details"]
    assert d["direction"] == "tightened"
    assert d["min_confidence"] > d["previous_min_confidence"]
    assert d["bad_fraction"] == 0.5


async def test_governor_writes_no_audit_when_nothing_changes(db, monkeypatch):
    """No change, no row: the log must not fill with non-events."""
    seen = _capture_audit(monkeypatch)
    await _seed_execs(db, "support", 5, safe=5)   # below the sample floor
    await run_autonomy_governor(db, T)
    assert [e for e in seen if e.get("resource_id") == "support"] == []
