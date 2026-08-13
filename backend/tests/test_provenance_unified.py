"""The unified provenance ledger (schema v2) - review P0 #2/#3.

One signed scheme, explicit parents, DB-serialized appends, and a verifier
that is honest about pre-unification history. These tests are the trust
artifact's evidence: round-trip verification across every writer facade,
real tamper detection, legacy honesty, race-retry, and the schema-level
no-fork guarantees.
"""
import uuid

import pytest
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from app.models.domain import ProvenanceLedger
from app.services.provenance import (
    LEDGER_SCHEMA_VERSION,
    TENANT_STREAM,
    ProvenanceEngine,
    append_ledger_event,
    verify_chain,
)


def _t():
    return f"tenant_prov_{uuid.uuid4().hex[:6]}"


async def _append(db, tenant, rule_id, n=1, **kw):
    entries = []
    for i in range(n):
        entries.append(await append_ledger_event(
            db, tenant_id=tenant, rule_id=rule_id, event_type=f"EVENT_{i}",
            actor_hash="system", actor_role="test", confidence_at=0.9,
            reasoning=f"entry {i}", **kw))
    return entries


async def test_round_trip_chain_verifies(db):
    tenant, rule = _t(), str(uuid.uuid4())
    e = await _append(db, tenant, rule, n=3)

    assert e[0].parent_id is None                 # genesis
    assert e[1].parent_id == e[0].id              # explicit parent pointers
    assert e[2].parent_id == e[1].id
    assert all(x.schema_version == LEDGER_SCHEMA_VERSION for x in e)

    verdict = await verify_chain(db, tenant, rule)
    assert verdict["status"] == "VERIFIED"
    assert verdict["chain_valid"] is True
    assert verdict["total"] == 3 and verdict["verified"] == 3
    assert verdict["invalid"] == [] and verdict["forks"] == []


async def test_every_writer_facade_lands_in_the_same_verifiable_scheme(db):
    """log_event (rules/skills path) and record_quantum_event (event stream)
    both write v2 entries that the one verifier accepts."""
    from app.services.quantum_ledger import QuantumLedgerEngine

    tenant, rule = _t(), str(uuid.uuid4())
    await ProvenanceEngine().log_event(
        db, rule_id=rule, event_type="CREATED", actor_hash="system",
        actor_role="extraction_engine", evidence_ids=[], confidence_at=0.8,
        reasoning="created", tenant_id=tenant)
    await ProvenanceEngine().log_event(
        db, rule_id=rule, event_type="VALIDATED", actor_hash="humanhash",
        actor_role="dept_head", evidence_ids=["ev1"], confidence_at=0.9,
        reasoning="validated", tenant_id=tenant)
    await QuantumLedgerEngine.record_quantum_event(
        db, "ACTION_APPLIED", "actuator", "applied",
        {"tenant_id": tenant, "action": "x"})

    rule_verdict = await verify_chain(db, tenant, rule)
    stream_verdict = await verify_chain(db, tenant, TENANT_STREAM)
    assert rule_verdict["status"] == "VERIFIED"
    assert stream_verdict["status"] == "VERIFIED"


async def test_tampering_is_detected(db):
    tenant, rule = _t(), str(uuid.uuid4())
    e = await _append(db, tenant, rule, n=2)

    # A DB-level edit outside the application (what tamper-evidence is FOR).
    await db.execute(
        update(ProvenanceLedger).where(ProvenanceLedger.id == e[1].id)
        .values(reasoning="history rewritten"))
    await db.commit()

    verdict = await verify_chain(db, tenant, rule)
    assert verdict["status"] == "TAMPERED"
    assert verdict["chain_valid"] is False
    assert e[1].id in verdict["invalid"]
    assert e[0].id not in verdict["invalid"]      # untouched entry still good


async def test_legacy_rows_are_reported_honestly_not_tampered(db):
    """Pre-unification rows (mixed schemes, even a random uuid4 'hash') must
    read as LEGACY_UNVERIFIABLE - the old false-TAMPERED was the P0 defect."""
    tenant, rule = _t(), str(uuid.uuid4())
    legacy = ProvenanceLedger(
        id=str(uuid.uuid4()), tenant_id=tenant, rule_id=rule,
        event_type="CLONED", actor_role="clone_engine",
        reasoning="old row", chain_hash=str(uuid.uuid4()))  # the uuid4 writer
    db.add(legacy)
    await db.commit()

    verdict = await verify_chain(db, tenant, rule)
    assert verdict["status"] == "LEGACY_UNVERIFIABLE"
    assert verdict["chain_valid"] is None
    assert verdict["legacy"] == 1

    # New v2 entries link to the legacy head for continuity and verify green.
    (e,) = await _append(db, tenant, rule, n=1)
    assert e.parent_id == legacy.id
    verdict = await verify_chain(db, tenant, rule)
    assert verdict["status"] == "VERIFIED"
    assert verdict["legacy"] == 1 and verdict["verified"] == 1


async def test_lost_head_race_retries_and_does_not_fork(db, monkeypatch):
    """If the writer reads a stale head (another worker appended first), the
    unique index rejects the insert and the writer retries against the new
    head - the chain stays linear."""
    import app.services.provenance as prov

    tenant, rule = _t(), str(uuid.uuid4())
    e = await _append(db, tenant, rule, n=2)  # head is e[1]

    real_chain_head = prov._chain_head
    calls = {"n": 0}

    async def stale_once(db_, tenant_id, scope):
        calls["n"] += 1
        if calls["n"] == 1:
            return e[0]  # stale: e[0] already has a child
        return await real_chain_head(db_, tenant_id, scope)

    monkeypatch.setattr(prov, "_chain_head", stale_once)
    entry = await append_ledger_event(
        db, tenant_id=tenant, rule_id=rule, event_type="RACED",
        actor_role="test", reasoning="raced append")

    assert calls["n"] >= 2                     # first attempt lost, retried
    assert entry.parent_id == e[1].id          # landed on the true head
    verdict = await verify_chain(db, tenant, rule)
    assert verdict["status"] == "VERIFIED" and verdict["forks"] == []


async def test_database_refuses_forks_and_second_genesis(db):
    """The no-fork guarantee is enforced by the schema, not by app code."""
    tenant, rule = _t(), str(uuid.uuid4())
    (genesis,) = await _append(db, tenant, rule, n=1)

    fork = ProvenanceLedger(
        id=str(uuid.uuid4()), tenant_id=tenant, rule_id=rule,
        event_type="FORK", chain_scope=rule,
        schema_version=LEDGER_SCHEMA_VERSION, parent_id=genesis.id,
        chain_hash=uuid.uuid4().hex)
    fork2 = ProvenanceLedger(
        id=str(uuid.uuid4()), tenant_id=tenant, rule_id=rule,
        event_type="FORK2", chain_scope=rule,
        schema_version=LEDGER_SCHEMA_VERSION, parent_id=genesis.id,
        chain_hash=uuid.uuid4().hex)
    db.add(fork)
    db.add(fork2)
    with pytest.raises(IntegrityError):        # two children of one parent
        await db.commit()
    await db.rollback()

    second_genesis = ProvenanceLedger(
        id=str(uuid.uuid4()), tenant_id=tenant, rule_id=rule,
        event_type="GENESIS2", chain_scope=rule,
        schema_version=LEDGER_SCHEMA_VERSION, parent_id=None,
        chain_hash=uuid.uuid4().hex)
    db.add(second_genesis)
    with pytest.raises(IntegrityError):        # partial unique on genesis
        await db.commit()
    await db.rollback()


async def test_chains_are_tenant_scoped(db):
    """Two tenants' streams never share a chain (RLS-compatible: each tenant
    can verify their own chain without reading anyone else's rows)."""
    from app.services.quantum_ledger import QuantumLedgerEngine

    t_a, t_b = _t(), _t()
    ea = await QuantumLedgerEngine.record_quantum_event(
        db, "E", "actor", "r", {"tenant_id": t_a})
    eb = await QuantumLedgerEngine.record_quantum_event(
        db, "E", "actor", "r", {"tenant_id": t_b})
    assert ea.parent_id is None and eb.parent_id is None  # separate geneses

    assert (await verify_chain(db, t_a, TENANT_STREAM))["status"] == "VERIFIED"
    assert (await verify_chain(db, t_b, TENANT_STREAM))["status"] == "VERIFIED"


async def test_unattributed_writes_are_refused(db):
    with pytest.raises(ValueError):
        await append_ledger_event(
            db, tenant_id="", event_type="X", reasoning="no tenant")


async def test_a_rule_created_via_the_api_verifies_clean(async_client):
    """The exact P0 repro: creating a rule through the API and then verifying
    its chain used to return false 'TAMPERED' because the route wrote a
    different hash scheme than the verifier recomputed."""
    r = await async_client.post("/api/v1/rules", json={
        "statement": "All refunds over $500 need manager approval",
        "domain": "support",
        "trigger_json": {"event": "refund_requested"},
        "action_json": {"action": "require_manager_approval"},
    })
    assert r.status_code in (200, 201), r.text
    rule_id = r.json()["id"]

    v = await async_client.get(f"/api/v1/provenance/{rule_id}/verify")
    assert v.status_code == 200, v.text
    verdict = v.json()
    assert verdict["status"] == "VERIFIED", verdict
    assert verdict["chain_valid"] is True
