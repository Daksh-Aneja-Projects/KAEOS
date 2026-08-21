"""The Company Brain proposes its own missions from real operational signals,
but never acts on its own: a proposal is inert until a human approves it, and
approval routes through the governed planner. These tests pin that boundary.

The brain also LEARNS: a rejected idea is suppressed for a cooldown, the weight
of a repeatedly-rejected KIND drops, and an approved proposal's outcome is
stamped from the mission it spawned.
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.models.brain import BrainProposal
from app.models.domain import Skill
from app.models.metrics_ts import MetricSample
from app.models.missions import Mission
from app.services import company_brain

pytestmark = pytest.mark.asyncio

T = "tenant_brain"


@pytest.fixture(autouse=True)
def _fake_llm(monkeypatch):
    # Never touch a real model in unit tests: skips both the proposal-rationale
    # polish and the planner's narrative enrichment on approve().
    monkeypatch.setenv("KAEOS_FAKE_LLM", "1")


def _now():
    return datetime.now(timezone.utc)


async def _seed_autonomy_decline(db, tid=T):
    """A safe-autonomy series that fell from ~0.92 (prior 24h) to ~0.60 (last
    24h) — a material, honest, real-row signal for the brain to observe."""
    now = _now()
    for i in range(4):
        db.add(MetricSample(tenant_id=tid, metric_key="safe_autonomy_rate",
                            value=0.92, interval="hour",
                            bucket_start=now - timedelta(hours=30 + i)))
        db.add(MetricSample(tenant_id=tid, metric_key="safe_autonomy_rate",
                            value=0.60, interval="hour",
                            bucket_start=now - timedelta(hours=1 + i)))
    await db.commit()


async def test_proposes_from_real_decline_but_stays_inert(db):
    await _seed_autonomy_decline(db)
    r = await company_brain.reflect_and_propose(db, T, use_llm=False)
    assert r["proposed"] >= 1
    props = (await db.execute(
        select(BrainProposal).where(BrainProposal.tenant_id == T))).scalars().all()
    p = next(p for p in props if p.signal_kind == "AUTONOMY_DECLINE")
    assert p.status == "PENDING"
    assert p.mission_id is None, "a proposal carries no action until approved"
    assert p.evidence and p.evidence[0]["kind"] == "metric", "grounded in a real row"


async def test_fresh_tenant_proposes_nothing(db):
    # No signals → the honest answer is silence, never a fabricated proposal.
    r = await company_brain.reflect_and_propose(db, "tenant_fresh", use_llm=False)
    assert r["observed"] == 0 and r["proposed"] == 0


async def test_approve_is_the_only_path_to_a_governed_mission(db):
    db.add(Skill(id=str(uuid.uuid4()), skill_id="fin_x", tenant_id=T,
                 department="finance", domain="finance", status="ACTIVE", confidence=0.9))
    await _seed_autonomy_decline(db)
    await company_brain.reflect_and_propose(db, T, use_llm=False)
    p = (await db.execute(select(BrainProposal).where(
        BrainProposal.tenant_id == T, BrainProposal.status == "PENDING").limit(1))).scalar_one()

    res = await company_brain.approve_proposal(db, T, p.id, "operator@acme")
    assert res["mission_id"]
    m = (await db.execute(select(Mission).where(Mission.id == res["mission_id"]))).scalar_one()
    assert m.goal == p.goal, "the governed mission carries the proposal's goal verbatim"
    await db.refresh(p)
    assert p.status == "APPROVED" and p.mission_id == m.id


async def test_double_approve_is_rejected(db):
    await _seed_autonomy_decline(db)
    await company_brain.reflect_and_propose(db, T, use_llm=False)
    p = (await db.execute(select(BrainProposal).where(
        BrainProposal.tenant_id == T, BrainProposal.status == "PENDING").limit(1))).scalar_one()
    await company_brain.approve_proposal(db, T, p.id, "op")
    with pytest.raises(ValueError):
        await company_brain.approve_proposal(db, T, p.id, "op")


async def test_rejection_suppresses_the_same_idea_for_the_cooldown(db):
    await _seed_autonomy_decline(db)
    await company_brain.reflect_and_propose(db, T, use_llm=False)
    p = (await db.execute(select(BrainProposal).where(
        BrainProposal.tenant_id == T).limit(1))).scalar_one()
    await company_brain.reject_proposal(db, T, p.id, "op", "not now")

    # The decline is still present, but the brain remembers the 'no'.
    r2 = await company_brain.reflect_and_propose(db, T, use_llm=False)
    assert r2["proposed"] == 0
    still_pending = (await db.execute(select(BrainProposal).where(
        BrainProposal.tenant_id == T, BrainProposal.status == "PENDING"))).scalars().all()
    assert still_pending == []


async def test_repeated_rejection_lowers_a_kinds_weight(db):
    for i in range(3):
        db.add(BrainProposal(tenant_id=T, title="t", goal="g", rationale="r", evidence=[],
                             signal_kind="COST_SPIKE", dedup_key=f"COST_SPIKE:s{i}",
                             status="REJECTED", decided_at=_now()))
    await db.commit()
    w = await company_brain._signal_kind_weight(db, T, "COST_SPIKE")
    assert w < 1.0, "a kind the human keeps rejecting should be de-prioritized"


async def test_outcome_is_reconciled_from_the_spawned_mission(db):
    m = Mission(tenant_id=T, goal="g", status="COMPLETED")
    db.add(m)
    await db.commit()
    p = BrainProposal(tenant_id=T, title="t", goal="g", rationale="r", evidence=[],
                      signal_kind="AUTONOMY_DECLINE", dedup_key="AUTONOMY_DECLINE:x",
                      status="APPROVED", mission_id=m.id)
    db.add(p)
    await db.commit()

    stamped = await company_brain._reconcile_outcomes(db, T)
    assert stamped == 1
    await db.refresh(p)
    assert p.outcome == "SUCCEEDED", "a completed mission closes the meta-loop"


async def test_connector_health_observer_fires_only_on_stale(db):
    from app.models.domain import Connector
    now = _now()
    db.add(Connector(tenant_id=T, name="Fresh CRM", status="CONNECTED",
                     last_sync_at=now - timedelta(minutes=10)))
    assert await company_brain._obs_connector_health(db, T) is None, \
        "a freshly-syncing connector is not a problem to propose about"

    db.add(Connector(tenant_id=T, name="Dead HRIS", status="CONNECTED",
                     last_sync_at=now - timedelta(days=3)))
    # Connected long ago but never synced counts as stale too.
    db.add(Connector(tenant_id=T, name="Never Synced ERP", status="CONNECTED",
                     connected_at=now - timedelta(days=2)))
    await db.commit()
    cand = await company_brain._obs_connector_health(db, T)
    assert cand is not None
    assert cand["signal_kind"] == "CONNECTOR_STALE"
    assert "2" in cand["title"], cand["title"]
    assert cand["evidence"][0]["kind"] == "connector"


async def test_knowledge_decay_observer_needs_a_real_backlog(db):
    from app.models.domain import Rule
    now = _now()

    def rule(**kw):
        return Rule(tenant_id=T, statement="s", trigger_json={}, action_json={},
                    is_archived=False, is_executable=True, half_life_days=90, **kw)

    # Four expired rules: below the threshold, the brain stays quiet.
    for _ in range(4):
        db.add(rule(validated_at=now - timedelta(days=200)))
    await db.commit()
    assert await company_brain._obs_knowledge_decay(db, T) is None

    # A fifth expired rule crosses it.
    db.add(rule(validated_at=now - timedelta(days=400)))
    # A fresh rule must not count.
    db.add(rule(validated_at=now - timedelta(days=1)))
    await db.commit()
    cand = await company_brain._obs_knowledge_decay(db, T)
    assert cand is not None
    assert cand["signal_kind"] == "KNOWLEDGE_DECAY"
    assert "5" in cand["title"], cand["title"]


async def test_strategic_fitness_observer_is_silent_on_an_empty_tenant(db):
    # A fresh tenant has fitness 1.0 and zero recommendations: the brain must
    # not fabricate a structural problem out of emptiness.
    cand = await company_brain._obs_strategic_fitness(db, "tenant_totally_empty")
    assert cand is None
