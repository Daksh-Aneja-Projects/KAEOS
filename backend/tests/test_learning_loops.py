"""Regressions for the learning/actuation loops.

1. Gate 5b FAILS CLOSED: a human-approved actuation that throws must not report
   SUCCESS_CLEAN, and the mission engine must mark the step FAILED.
2. The L1 vocabulary split: a measured BAD outcome is never mined as gold, and a
   HITL approval carrying an edit is stamped SUCCESS_WITH_EDIT.
3. L4 outcomes are attributed to the mission's real step executions.
4. Enterprise memory is written after a governed decision and read back before
   the next one.
5. A federated swarm hash match alone does not grant the VALIDATED_PEER tier.
6. A permanently failing fine-tune poll dead-letters instead of retrying forever.
"""
import uuid

import pytest
from sqlalchemy import select

from app.agents.runtime import AgentExecutor
from app.models.domain import Skill, SkillExecution
from app.models.event_mesh import ExternalSignal
from app.models.foundry import FineTuneJob, LABEL_GOLD, LABEL_NEGATIVE
from app.models.intelligence_metrics import OutcomeRecord
from app.models.missions import Mission, MissionStep
from app.services.foundry import dataset_builder
from app.services.foundry.finetune import FineTuneProvider, poll_finetune_jobs
from app.services.missions import engine as mission_engine


# ── Shared executor fakes (same shape as test_gate_integrity) ────────────

class _FakeHITL:
    async def request_human_confirmation(self, skill, context):
        return {"pending": True, "execution_id": context.get("execution_id", "x")}


class _FakeCompliance:
    async def check_before_execution(self, tags, context):
        return []

    def enforce_audit_requirements(self, *a, **k):
        return True


class _FakeRouter:
    def confidence_ceiling(self, model_tier="reasoning"):
        return 1.0


class _FakeExecEngine:
    async def run(self, skill, context, execution_id, tenant_id, skill_obj=None,
                  compliance_warnings=None):
        return {"status": "SUCCESS_CLEAN", "reasoning_chain": [{"decision": "do it"}],
                "execution_id": execution_id, "steps_completed": 2, "duration_ms": 7}


class _FakeFeed:
    def __init__(self):
        self.events = []

    async def emit(self, **kwargs):
        self.events.append(kwargs)


def _executor(monkeypatch):
    from app.services import llm_router as lr

    async def fake_for_tenant(cls, tenant_id):
        return _FakeRouter()

    monkeypatch.setattr(lr.LLMRouter, "for_tenant", classmethod(fake_for_tenant))
    ex = AgentExecutor(_FakeCompliance(), _FakeHITL())
    ex._exec_engine = _FakeExecEngine()
    ex._activity_feed = _FakeFeed()
    return ex


# ── 1: Gate 5b fails closed ──────────────────────────────────────────────

async def test_actuation_failure_does_not_report_success(monkeypatch):
    """The skill produced output but the governed write threw: the execution is
    FAILED_ACTUATION, and the partial-failure fact is surfaced distinctly."""
    ex = _executor(monkeypatch)

    from app.services.actuation import Actuator

    async def boom(*a, **k):
        raise RuntimeError("SoR refused the write")

    monkeypatch.setattr(Actuator, "apply_action", staticmethod(boom))

    skill = {"skill_id": "ops_write", "confidence": 0.99, "compliance_tags": [],
             "steps": [{"step": 1, "name": "Do", "prompt": "x"}],
             "actuation": {"system": "sandbox", "object_type": "record",
                           "external_id": "emp_42", "operation": "UPDATE",
                           "payload": {"status": "onboarded"}}}
    out = await ex.execute_skill(
        skill, {"tenant_id": "t_act", "execution_id": "e-act"}, hitl_pre_approved=True)

    assert out["status"] == "FAILED_ACTUATION", "a failed governed write must not report success"
    assert out["skill_output_produced"] is True      # partial failure, stated plainly
    assert "sandbox:emp_42" in out["reason"]
    assert out["steps_completed"] == 2               # the reasoning facts survive
    assert any(e.get("requires_action") for e in ex._activity_feed.events)


async def test_actuation_failure_fails_the_mission_step(db):
    """The mission engine must take the failure branch: the step is FAILED, not DONE."""
    mission = Mission(id=str(uuid.uuid4()), tenant_id="t_act", goal="g", status="RUNNING")
    step = MissionStep(id=str(uuid.uuid4()), tenant_id="t_act", mission_id=mission.id,
                       seq=1, name="write it", department="operations",
                       skill_id="ops_write", status="RUNNING")
    db.add_all([mission, step])
    await db.commit()

    mission_engine._apply_step_result(db, mission, step, {
        "status": "FAILED_ACTUATION", "reason": "Approved write to sandbox:emp_42 failed: boom",
        "skill_output_produced": True, "steps_completed": 2,
    })
    assert step.status == "FAILED"
    assert "sandbox:emp_42" in (step.result_summary or "")
    assert mission.spent_usd in (None, 0.0)


# ── 2: the L1 vocabulary split ───────────────────────────────────────────

async def test_bad_measured_outcome_is_never_mined_as_gold(db):
    """A clean autonomous execution that reality judged BAD must be mined as a
    NEGATIVE contrastive example, not as LABEL_GOLD training data."""
    t = "tenant_mine"
    good_ex = SkillExecution(id=str(uuid.uuid4()), tenant_id=t, skill_id_name="ops.a",
                             status="SUCCESS_CLEAN", outcome_type="SUCCESS_CLEAN",
                             hitl_required=False, task_intent="do a",
                             reasoning_chain=[{"decision": "did a"}])
    bad_ex = SkillExecution(id=str(uuid.uuid4()), tenant_id=t, skill_id_name="ops.b",
                            status="SUCCESS_CLEAN", outcome_type="SUCCESS_CLEAN",
                            hitl_required=False, task_intent="do b",
                            reasoning_chain=[{"decision": "did b"}])
    db.add_all([good_ex, bad_ex])
    db.add(OutcomeRecord(tenant_id=t, execution_id=bad_ex.id, skill_id_name="ops.b",
                         outcome="BAD"))
    await db.commit()

    res = await dataset_builder.mine_executions(db, t, include_negative=True)
    assert res["by_label"].get(LABEL_GOLD) == 1
    assert res["by_label"].get(LABEL_NEGATIVE) == 1

    from app.models.foundry import TrainingExample
    mined = {e.source_execution_id: e for e in (await db.execute(
        select(TrainingExample).where(TrainingExample.tenant_id == t))).scalars().all()}
    assert mined[bad_ex.id].evaluation_label == LABEL_NEGATIVE
    assert mined[bad_ex.id].ideal_answer is None      # never presented as an answer to copy
    assert mined[good_ex.id].evaluation_label == LABEL_GOLD


@pytest.fixture
def mute_feed(monkeypatch):
    """The feed write is not under test and the app-engine test DB lacks its table."""
    from app.services.activity_feed import ActivityFeedService

    async def _noop(self, **kwargs):
        return None

    monkeypatch.setattr(ActivityFeedService, "emit", _noop)


async def test_hitl_approval_with_edit_stamps_success_with_edit(db, mute_feed):
    """An approval carrying a correction is human-EDITED fallout, not clean
    autonomy, and the correction becomes a training example."""
    from app.api.routes.skills import approve_hitl, ApproveHitlIn

    t = "tenant_edit"
    ex = SkillExecution(id=str(uuid.uuid4()), tenant_id=t, skill_id_name="hr.offer",
                        status="PENDING_HITL", outcome_type="PENDING_HITL",
                        hitl_required=True, task_intent="draft the offer",
                        reasoning_chain=[{"decision": "offer 100k"}])
    db.add(ex)
    await db.commit()

    tenant = {"tenant_id": t, "role": "operator", "email": "hr@acme"}
    await approve_hitl(ex.id, ApproveHitlIn(corrected_answer="offer 110k"),
                       tenant=tenant, db=db)

    refreshed = (await db.execute(
        select(SkillExecution).where(SkillExecution.id == ex.id))).scalar_one()
    assert refreshed.outcome_type == "SUCCESS_WITH_EDIT"
    assert refreshed.hitl_approved is True

    from app.models.foundry import TrainingExample
    correction = (await db.execute(
        select(TrainingExample).where(TrainingExample.source_execution_id == ex.id))).scalar_one()
    assert correction.ideal_answer == "offer 110k"
    assert correction.human_verified is True


async def test_plain_approval_stays_success_clean(db, mute_feed):
    from app.api.routes.skills import approve_hitl

    t = "tenant_plain"
    ex = SkillExecution(id=str(uuid.uuid4()), tenant_id=t, skill_id_name="hr.offer",
                        status="PENDING_HITL", outcome_type="PENDING_HITL", hitl_required=True)
    db.add(ex)
    await db.commit()

    await approve_hitl(ex.id, None, tenant={"tenant_id": t, "role": "operator"}, db=db)
    refreshed = (await db.execute(
        select(SkillExecution).where(SkillExecution.id == ex.id))).scalar_one()
    assert refreshed.outcome_type == "SUCCESS_CLEAN"


def test_time_machine_recognises_the_edited_class():
    """An approved-with-edit execution: hitl_required, clean status, edited outcome."""
    from app.services.time_machine import _classify
    assert _classify(True, "SUCCESS_CLEAN", "SUCCESS_WITH_EDIT") == "edited"
    assert _classify(True, "SUCCESS_CLEAN", "SUCCESS_CLEAN") == "routed_to_human"


# ── 3: L4 outcomes attach to real executions ─────────────────────────────

async def test_mission_outcomes_attach_to_step_execution_ids(db):
    t = "tenant_l4attr"
    m = Mission(id=str(uuid.uuid4()), tenant_id=t, goal="mitigate",
                status="COMPLETED_WITH_EXCEPTIONS", created_by="event-mesh")
    db.add(m)
    db.add(ExternalSignal(id=str(uuid.uuid4()), tenant_id=t, kind="VENDOR",
                          title="outage", response_kind="MISSION",
                          response_ref=m.id, status="RESPONDED"))
    db.add(MissionStep(id=str(uuid.uuid4()), tenant_id=t, mission_id=m.id, seq=1,
                       name="a", department="operations", skill_id="ops.a",
                       status="DONE", execution_id="exec-a", hitl_required=False))
    db.add(MissionStep(id=str(uuid.uuid4()), tenant_id=t, mission_id=m.id, seq=2,
                       name="b", department="finance", skill_id="fin.b",
                       status="FAILED", execution_id="exec-b", hitl_required=True))
    await db.commit()

    await mission_engine._writeback_signal_on_finish(db, m)
    await db.commit()

    recs = {r.execution_id: r for r in (await db.execute(
        select(OutcomeRecord).where(OutcomeRecord.tenant_id == t))).scalars().all()}
    assert set(recs) == {"exec-a", "exec-b"}, "outcomes must join to real executions"
    assert recs["exec-a"].outcome == "GOOD" and recs["exec-a"].skill_id_name == "ops.a"
    assert recs["exec-b"].outcome == "BAD" and recs["exec-b"].autonomous is False
    assert not any(str(r.skill_id_name or "").startswith("mission:") for r in recs.values())

    sig = (await db.execute(
        select(ExternalSignal).where(ExternalSignal.response_ref == m.id))).scalar_one()
    assert sig.status == "RESOLVED"


# ── 4: enterprise memory is written and read ─────────────────────────────

async def test_decision_memory_is_stored_and_recalled():
    from app.services.memory.enterprise_memory import EnterpriseMemoryService

    t = f"tenant_mem_{uuid.uuid4().hex[:6]}"
    ctx = "finance.dunning: chase the overdue ACME invoice"
    mem_id = await EnterpriseMemoryService.store_decision_memory(
        None, t, ctx, {"skill_id": "finance.dunning"}, outcome="SUCCESS_CLEAN")
    assert mem_id

    hits = await EnterpriseMemoryService.recall_similar_situations(None, t, ctx, limit=3)
    assert hits, "a stored decision must be recallable"
    assert any(h["id"] == mem_id for h in hits)

    # Tenant-scoped: another tenant never sees it.
    assert await EnterpriseMemoryService.recall_similar_situations(
        None, f"{t}_other", ctx, limit=3) == []


async def test_executor_injects_recalled_decisions_into_context(monkeypatch):
    """The recall runs before deliberation and lands on the context the executor
    renders into the prompt."""
    ex = _executor(monkeypatch)
    from app.services.memory import enterprise_memory as mem

    async def fake_recall(db, tenant_id, current_context, limit=3):
        return [{"id": "m1", "content": "we escalated last time", "similarity": 0.91,
                 "memory_type": "DECISION", "metadata": {}}]

    stored = {}

    async def fake_store(db, tenant_id, context, decision, outcome="UNKNOWN"):
        stored.update({"tenant_id": tenant_id, "context": context, "outcome": outcome})
        return "m2"

    monkeypatch.setattr(mem.EnterpriseMemoryService, "recall_similar_situations",
                        staticmethod(fake_recall))
    monkeypatch.setattr(mem.EnterpriseMemoryService, "store_decision_memory",
                        staticmethod(fake_store))

    seen = {}

    class _Capture(_FakeExecEngine):
        async def run(self, skill, context, execution_id, tenant_id, **kw):
            seen["prior"] = context.get("prior_decisions")
            return await super().run(skill, context, execution_id, tenant_id, **kw)

    ex._exec_engine = _Capture()
    ctx = {"tenant_id": "t_mem", "execution_id": "e-mem", "task_intent": "chase invoice"}
    out = await ex.execute_skill({"skill_id": "finance.dunning", "confidence": 0.99,
                                  "compliance_tags": [], "steps": []}, ctx)

    assert out["status"] == "SUCCESS_CLEAN"
    assert seen["prior"] == [{"summary": "we escalated last time", "similarity": 0.91}]
    assert stored["tenant_id"] == "t_mem"
    assert "chase invoice" in stored["context"]


async def test_memory_failure_never_blocks_a_decision(monkeypatch):
    ex = _executor(monkeypatch)
    from app.services.memory import enterprise_memory as mem

    async def boom(*a, **k):
        raise RuntimeError("vector store down")

    monkeypatch.setattr(mem.EnterpriseMemoryService, "recall_similar_situations",
                        staticmethod(boom))
    monkeypatch.setattr(mem.EnterpriseMemoryService, "store_decision_memory",
                        staticmethod(boom))

    out = await ex.execute_skill(
        {"skill_id": "finance.dunning", "confidence": 0.99, "compliance_tags": [], "steps": []},
        {"tenant_id": "t_mem2", "execution_id": "e-mem2"})
    assert out["status"] == "SUCCESS_CLEAN"


# ── 5: a peer hash match is not evidence ─────────────────────────────────

async def test_swarm_boost_needs_local_evidence_for_the_peer_tier(db):
    from app.services.federated_engine import FederatedEngine

    t = "tenant_fed"
    unproven = Skill(id=str(uuid.uuid4()), skill_id="ops.unproven", tenant_id=t,
                     department="operations", domain="operations", status="ACTIVE",
                     confidence=0.5, confidence_tier="UNVALIDATED")
    proven = Skill(id=str(uuid.uuid4()), skill_id="ops.proven", tenant_id=t,
                   department="operations", domain="operations", status="ACTIVE",
                   confidence=0.5, confidence_tier="UNVALIDATED")
    db.add_all([unproven, proven])
    for i in range(3):
        db.add(SkillExecution(id=str(uuid.uuid4()), tenant_id=t, skill_id_name="ops.proven",
                              status="SUCCESS_CLEAN", hitl_required=False))
    await db.commit()

    assert await FederatedEngine._local_success_evidence(db, t, "ops.unproven") == 0
    assert await FederatedEngine._local_success_evidence(db, t, "ops.proven") == 3


# ── 6: a broken fine-tune poll dead-letters ──────────────────────────────

class _BrokenProvider(FineTuneProvider):
    name = "broken"

    async def submit(self, *, base_model, examples):
        return "ftjob-broken"

    async def poll(self, external_job_id):
        raise RuntimeError("provider handle is gone")


async def test_finetune_poll_dead_letters_after_bounded_errors(db):
    from app.services.foundry.finetune import _MAX_POLL_ERRORS

    t = "tenant_ftdl"
    job = FineTuneJob(id=str(uuid.uuid4()), tenant_id=t, tier="fast", provider="broken",
                      base_model="b", external_job_id="ftjob-broken", status="RUNNING")
    db.add(job)
    await db.commit()

    prov = _BrokenProvider()
    for _ in range(_MAX_POLL_ERRORS - 1):
        await poll_finetune_jobs(db, tenant_id=t, provider=prov)
    refreshed = (await db.execute(select(FineTuneJob).where(FineTuneJob.id == job.id))).scalar_one()
    assert refreshed.status == "RUNNING"
    assert refreshed.poll_errors == _MAX_POLL_ERRORS - 1     # streak persisted

    res = await poll_finetune_jobs(db, tenant_id=t, provider=prov)
    assert res["advanced"] == 1
    refreshed = (await db.execute(select(FineTuneJob).where(FineTuneJob.id == job.id))).scalar_one()
    assert refreshed.status == "FAILED"
    assert "dead-lettered" in (refreshed.error or "")


async def test_finetune_poll_error_streak_resets_on_success(db):
    t = "tenant_ftreset"
    job = FineTuneJob(id=str(uuid.uuid4()), tenant_id=t, tier="fast", provider="x",
                      base_model="b", external_job_id="ftjob-1", status="RUNNING",
                      poll_errors=4)
    db.add(job)
    await db.commit()

    class _Recovered(FineTuneProvider):
        name = "recovered"

        async def submit(self, *, base_model, examples):
            return "ftjob-1"

        async def poll(self, external_job_id):
            return {"status": "RUNNING"}

    await poll_finetune_jobs(db, tenant_id=t, provider=_Recovered())
    refreshed = (await db.execute(select(FineTuneJob).where(FineTuneJob.id == job.id))).scalar_one()
    assert refreshed.poll_errors == 0
    assert refreshed.status == "RUNNING"
