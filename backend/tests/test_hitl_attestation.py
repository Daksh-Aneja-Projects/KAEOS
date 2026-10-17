"""
Review attestation: what the deciding surface MEASURED about the human's own
review (how long the item was on screen, whether the predicted diff and the
reasoning were shown), server-stamped and stored with the decision.

The rules pinned here:
  * the client sends measurements, never conclusions: ``quick`` and ``present``
    are derived on the server, and ``approver`` / ``decided_at`` are the server's;
  * a decision with no attestation (an older client, the e-mail link) is recorded
    as ABSENT - never as a quick or an attended review;
  * a decision made in under QUICK_DECISION_SECONDS is labelled quick (a label,
    not a verdict: the decision stands);
  * ``resolve_hitl`` stores the attestation on the pause record and merges it into
    the execution's context as ``hitl_attestation`` without replacing the context.
"""
import asyncio
import math
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.domain import SkillExecution
from app.services.hitl_manager import (
    QUICK_DECISION_SECONDS,
    HITLManager,
    normalize_attestation,
)

MAX_SECONDS = 7 * 24 * 3600.0


def _norm(raw, *, approver="sam@example.com", approved=True):
    return normalize_attestation(raw, approver=approver, approved=approved)


# ── normalize_attestation ─────────────────────────────────────────────────────

def test_the_quick_threshold_is_five_seconds():
    assert QUICK_DECISION_SECONDS == 5.0


@pytest.mark.parametrize("raw", [None, "yes", 5, [], ["seconds_visible"], True])
def test_no_attestation_is_recorded_as_absent_not_as_a_review(raw):
    out = _norm(raw, approver="sam@example.com", approved=True)
    assert out["present"] is False
    assert out["approver"] == "sam@example.com" and out["approved"] is True
    assert out["quick_threshold_seconds"] == QUICK_DECISION_SECONDS
    # nothing the surface did not measure is invented: no quick flag, no seconds
    assert "quick" not in out and "seconds_visible" not in out
    assert "diff_shown" not in out and "reasoning_shown" not in out
    stamped = datetime.fromisoformat(out["decided_at"])
    assert stamped.tzinfo is not None
    assert abs((datetime.now(timezone.utc) - stamped).total_seconds()) < 30


def test_an_empty_attestation_is_present_false_and_never_quick():
    out = _norm({})
    assert out["present"] is False and out["quick"] is False
    assert out["seconds_visible"] is None
    assert out["channel"] == "console"


@pytest.mark.parametrize("raw", [None, "abc", "", [], {}, "not-a-number"])
def test_an_unreadable_seconds_value_is_treated_as_absent(raw):
    out = _norm({"seconds_visible": raw, "diff_shown": True})
    assert out["present"] is False and out["seconds_visible"] is None
    assert out["quick"] is False
    assert out["diff_shown"] is True, "the other measurements still stand"


@pytest.mark.parametrize("seconds,quick", [
    (3, True), (3.0, True), (0, True), (0.001, True), (4.999, True),
    (5, False), (5.0, False), (5.001, False), (12, False), (300, False),
])
def test_under_the_threshold_is_quick_and_at_or_over_it_is_not(seconds, quick):
    out = _norm({"seconds_visible": seconds})
    assert out["present"] is True
    assert out["seconds_visible"] == float(seconds)
    assert out["quick"] is quick
    assert out["quick_threshold_seconds"] == 5.0


def test_numeric_strings_are_read_as_numbers():
    assert _norm({"seconds_visible": "4"})["quick"] is True
    assert _norm({"seconds_visible": " 30.5 "})["seconds_visible"] == 30.5


def test_negative_seconds_are_clamped_to_zero_and_so_are_quick():
    out = _norm({"seconds_visible": -5})
    assert out["seconds_visible"] == 0.0 and out["present"] is True and out["quick"] is True


@pytest.mark.parametrize("huge", [1e12, 10 ** 18, float("inf"), "inf", 7 * 24 * 3600 + 1])
def test_huge_seconds_are_clamped_to_one_week(huge):
    out = _norm({"seconds_visible": huge})
    assert out["seconds_visible"] == MAX_SECONDS
    assert out["present"] is True and out["quick"] is False


def test_negative_infinity_is_clamped_to_zero_and_so_is_quick():
    out = _norm({"seconds_visible": float("-inf")})
    assert out["seconds_visible"] == 0.0 and out["quick"] is True


# Fixed the same session it was found: NaN is treated as absent (see normalize_attestation).
@pytest.mark.parametrize("nan", [float("nan"), "nan", "NaN"])
def test_nan_seconds_must_not_become_an_attended_review(nan):
    out = _norm({"seconds_visible": nan})
    assert out["present"] is False
    assert out["seconds_visible"] is None or math.isfinite(out["seconds_visible"])


def test_the_diff_and_reasoning_flags_count_only_a_real_true():
    # Launch audit 2026-10-17: bool("false") is True, so a client sending the
    # string "false" was recorded as having shown the diff. Only JSON true counts.
    out = _norm({"seconds_visible": 20, "diff_shown": True, "reasoning_shown": True})
    assert out["diff_shown"] is True and out["reasoning_shown"] is True
    out = _norm({"seconds_visible": 20, "diff_shown": 1, "reasoning_shown": "yes"})
    assert out["diff_shown"] is False and out["reasoning_shown"] is False
    out = _norm({"seconds_visible": 20, "diff_shown": "false", "reasoning_shown": "true"})
    assert out["diff_shown"] is False and out["reasoning_shown"] is False
    out = _norm({"seconds_visible": 20, "diff_shown": 0, "reasoning_shown": None})
    assert out["diff_shown"] is False and out["reasoning_shown"] is False
    out = _norm({"seconds_visible": 20})
    assert out["diff_shown"] is False and out["reasoning_shown"] is False


def test_the_channel_is_truncated_to_32_characters_and_defaults_to_console():
    assert _norm({"seconds_visible": 9, "channel": "x" * 50})["channel"] == "x" * 32
    assert _norm({"seconds_visible": 9, "channel": "y" * 32})["channel"] == "y" * 32
    assert _norm({"seconds_visible": 9, "channel": "slack"})["channel"] == "slack"
    assert _norm({"seconds_visible": 9})["channel"] == "console"
    assert _norm({"seconds_visible": 9, "channel": ""})["channel"] == "console"
    assert _norm({"seconds_visible": 9, "channel": None})["channel"] == "console"
    assert _norm({"seconds_visible": 9, "channel": 12345})["channel"] == "12345"


def test_the_client_cannot_claim_its_own_conclusions_or_identity():
    # a client that says "not quick" about 1 second is overruled by its own measurement
    liar = _norm({"seconds_visible": 1, "quick": False, "present": True,
                  "approver": "ceo@example.com", "approved": False,
                  "decided_at": "1999-01-01T00:00:00+00:00"},
                 approver="sam@example.com", approved=True)
    assert liar["quick"] is True
    assert liar["approver"] == "sam@example.com" and liar["approved"] is True
    assert liar["decided_at"].startswith(str(datetime.now(timezone.utc).year))
    # and one that claims "quick" about 30 seconds is overruled the other way
    assert _norm({"seconds_visible": 30, "quick": True})["quick"] is False
    # a client cannot manufacture a presence it did not measure
    assert _norm({"present": True, "quick": False})["present"] is False


def test_approved_is_coerced_to_a_boolean_and_the_approver_is_the_servers():
    out = _norm({"seconds_visible": 8}, approver="sam@example.com", approved=0)
    assert out["approved"] is False and out["approver"] == "sam@example.com"
    assert _norm(None, approver="x", approved=1)["approved"] is True


# ── resolve_hitl stores the attestation ───────────────────────────────────────

class _NoRedisHITLManager(HITLManager):
    async def _get_redis(self):
        return None


@pytest.fixture(autouse=True)
def _mute_activity_feed(monkeypatch):
    """The feed write is not under test and the test DB may lack its table."""
    from app.services.activity_feed import ActivityFeedService

    async def _noop(self, **kwargs):
        return None

    monkeypatch.setattr(ActivityFeedService, "emit", _noop)


@pytest.fixture(autouse=True)
def _mute_notifier(monkeypatch):
    """Not under test, and its fire-and-forget task would open a concurrent session on
    the in-memory StaticPool's single shared connection."""
    from app.services import notifier

    monkeypatch.setattr(notifier, "notify_fire_and_forget", lambda *a, **k: None)


@pytest.fixture(autouse=True)
def _mute_event_bus(monkeypatch):
    """The decision event is published after the commit; it is not under test."""
    from app.services import event_bus as eb

    async def _emit(*a, **k):
        return None

    monkeypatch.setattr(eb.event_bus, "emit", _emit)


def _pending(exec_id, tenant="tenant_attest", **context):
    return {
        "exec_id": exec_id, "skill_id": "attest_skill", "tenant_id": tenant,
        "status": "PENDING", "decision": None, "approver": None, "reason": None,
        # The pause has been waiting a minute: an attestation of up to 60 s on
        # screen is possible; more is clamped (normalize_attestation).
        "created_at": (datetime.now(timezone.utc) - timedelta(seconds=60)).isoformat(),
        "skill_def": {"skill_id": "attest_skill", "steps": [], "department": "support"},
        "context": {"intent": "refund", "amount": 40, **context},
    }


def _manager_with_recorded_resume():
    mgr = _NoRedisHITLManager()
    resumed = []

    async def _resume(execution_id, fallback_record=None):
        resumed.append((execution_id, fallback_record))
        return True

    mgr._resume_from_hitl = _resume
    return mgr, resumed


async def test_resolve_hitl_stores_a_quick_attestation_on_the_record_and_in_its_context():
    mgr, resumed = _manager_with_recorded_resume()
    exec_id = f"exec-att-{uuid.uuid4().hex[:8]}"
    await mgr._put_record(exec_id, _pending(exec_id))

    ok = await mgr.resolve_hitl(exec_id, True, "sam@example.com",
                                attestation={"seconds_visible": 2})
    assert ok is True
    await asyncio.sleep(0)                      # let the scheduled resume run
    assert [r[0] for r in resumed] == [exec_id]

    record = await mgr._get_record(exec_id)
    att = record["attestation"]
    assert att["present"] is True and att["quick"] is True
    assert att["seconds_visible"] == 2.0 and att["approver"] == "sam@example.com"
    assert att["approved"] is True
    assert record["context"]["hitl_attestation"] == att
    assert record["context"]["hitl_attestation"] is att, "one stamped dict, stored in both places"
    # the original context survives the merge
    assert record["context"]["intent"] == "refund" and record["context"]["amount"] == 40
    # and the decision itself is recorded as before
    assert record["status"] == "RESOLVED" and record["decision"] is True
    assert record["approver"] == "sam@example.com" and record["resolved_at"]
    # the resume is handed the same record, so a gated run's proof carries the attestation
    assert resumed[0][1]["context"]["hitl_attestation"]["quick"] is True


async def test_resolve_hitl_an_attended_decision_is_not_quick():
    mgr, _ = _manager_with_recorded_resume()
    exec_id = f"exec-att-{uuid.uuid4().hex[:8]}"
    await mgr._put_record(exec_id, _pending(exec_id))
    await mgr.resolve_hitl(exec_id, True, "sam@example.com", attestation={
        "seconds_visible": 12, "diff_shown": True, "reasoning_shown": True, "channel": "console"})
    await asyncio.sleep(0)
    att = (await mgr._get_record(exec_id))["attestation"]
    assert att["present"] is True and att["quick"] is False
    assert att["diff_shown"] is True and att["reasoning_shown"] is True


async def test_resolve_hitl_without_an_attestation_records_it_as_absent():
    mgr, _ = _manager_with_recorded_resume()
    exec_id = f"exec-att-{uuid.uuid4().hex[:8]}"
    await mgr._put_record(exec_id, _pending(exec_id))
    assert await mgr.resolve_hitl(exec_id, True, "link-approver@example.com") is True
    await asyncio.sleep(0)
    record = await mgr._get_record(exec_id)
    assert record["attestation"]["present"] is False
    assert "quick" not in record["attestation"]
    assert record["context"]["hitl_attestation"] == record["attestation"]


async def test_resolve_hitl_a_rejection_carries_the_attestation_too():
    mgr, resumed = _manager_with_recorded_resume()
    exec_id = f"exec-att-{uuid.uuid4().hex[:8]}"
    await mgr._put_record(exec_id, _pending(exec_id))
    ok = await mgr.resolve_hitl(exec_id, False, "sam@example.com", reason="wrong amount",
                                attestation={"seconds_visible": 3})
    assert ok is True
    await asyncio.sleep(0)
    assert resumed == [], "a rejection never resumes the run"
    record = await mgr._get_record(exec_id)
    assert record["decision"] is False and record["reason"] == "wrong amount"
    assert record["attestation"]["approved"] is False
    assert record["attestation"]["quick"] is True
    assert record["context"]["hitl_attestation"] is record["attestation"]


async def test_another_tenant_cannot_resolve_or_attest_a_pending_record():
    mgr, resumed = _manager_with_recorded_resume()
    exec_id = f"exec-att-{uuid.uuid4().hex[:8]}"
    await mgr._put_record(exec_id, _pending(exec_id, tenant="tenant_owner"))
    ok = await mgr.resolve_hitl(exec_id, True, "mallory@example.com", tenant_id="tenant_other",
                                attestation={"seconds_visible": 99})
    assert ok is False
    await asyncio.sleep(0)
    record = await mgr._get_record(exec_id)
    assert record["status"] == "PENDING" and "attestation" not in record
    assert "hitl_attestation" not in record["context"] and resumed == []


async def test_resolve_hitl_merges_the_attestation_into_the_execution_row_context():
    """The DB row is the source of truth: a /skills-route pause with no cache record is
    resolved from the row alone, and the attestation rides in its context."""
    mgr = _NoRedisHITLManager()
    exec_id = f"exec-att-{uuid.uuid4().hex[:8]}"
    async with AsyncSessionLocal() as s:
        s.add(SkillExecution(
            id=exec_id, skill_id_name="attest_skill", tenant_id="tenant_attest",
            status="PENDING_HITL", agent_state="PAUSED", hitl_required=True,
            context={"intent": "refund", "amount": 40}, reasoning_chain=[]))
        await s.commit()

    ok = await mgr.resolve_hitl(exec_id, False, "sam@example.com", reason="no",
                                tenant_id="tenant_attest", attestation={"seconds_visible": 3})
    assert ok is True
    async with AsyncSessionLocal() as s:
        row = (await s.execute(
            select(SkillExecution).where(SkillExecution.id == exec_id))).scalar_one()
    assert row.hitl_approved is False and row.hitl_approver == "sam@example.com"
    assert row.status == "HUMAN_OVERRIDDEN"
    att = row.context["hitl_attestation"]
    assert att["present"] is True and att["quick"] is True and att["approved"] is False
    assert att["approver"] == "sam@example.com"
    # merged, never replacing the context the resumed run reads
    assert row.context["intent"] == "refund" and row.context["amount"] == 40


async def test_a_gate_pause_decided_with_an_attestation_stores_it_on_record_and_row():
    mgr = _NoRedisHITLManager()
    exec_id = f"exec-att-{uuid.uuid4().hex[:8]}"
    skill = {"skill_id": "attest_gate", "department": "support",
             "steps": [{"step": 1, "name": "Assess", "prompt": "Assess."}],
             "compliance_tags": [], "confidence": 0.5}
    ctx = {"execution_id": exec_id, "tenant_id": "tenant_attest", "instruction": "refund 40"}
    out = await mgr.request_human_confirmation(skill, ctx)
    assert out["pending"] is True
    # the reviewer looked at it for a minute before deciding
    rec = await mgr._get_record(exec_id)
    rec["created_at"] = (datetime.now(timezone.utc) - timedelta(seconds=60)).isoformat()
    await mgr._put_record(exec_id, rec)

    assert await mgr.resolve_hitl(exec_id, False, "sam@example.com", reason="no",
                                  attestation={"seconds_visible": 30, "diff_shown": True}) is True
    record = await mgr._get_record(exec_id)
    assert record["attestation"]["quick"] is False and record["attestation"]["diff_shown"] is True
    assert record["context"]["hitl_attestation"] is record["attestation"]
    async with AsyncSessionLocal() as s:
        row = (await s.execute(
            select(SkillExecution).where(SkillExecution.id == exec_id))).scalar_one()
    assert row.context["hitl_attestation"]["quick"] is False
    assert row.context["hitl_attestation"]["diff_shown"] is True
    assert row.context["instruction"] == "refund 40"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


# ── launch audit 2026-10-17 (H3 + attestation honesty) ───────────────────────

def test_an_agent_principal_cannot_decide_a_paused_run():
    from fastapi import HTTPException
    from app.core.tenant import require_human_decider
    gate = require_human_decider("operator")
    assert gate(tenant={"tenant_id": "t", "role": "operator", "email": "a@example.com"})
    for agent in ({"tenant_id": "t", "role": "operator", "key_id": "k1", "name": "bot"},
                  {"tenant_id": "t", "role": "operator",
                   "gateway_principal": {"kind": "oidc", "id": "g1", "name": "bot"}}):
        with pytest.raises(HTTPException) as e:
            gate(tenant=agent)
        assert e.value.status_code == 403 and "Only a person" in e.value.detail
    with pytest.raises(HTTPException):
        gate(tenant={"tenant_id": "t", "role": "viewer"})


def test_every_hitl_decision_route_uses_the_human_gate():
    """Pins the route table: an approve / reject / resolve route that only
    checks a role would let an agent key approve its own pause again."""
    from app.main import app
    decide = [r for r in app.routes if getattr(r, "methods", None) and "POST" in r.methods
              and "hitl" in r.path.split("/")
              and (r.path.rsplit("/", 1)[-1] in ("approve", "reject", "resolve", "hitl"))]
    assert len(decide) >= 8, [r.path for r in decide]
    for r in decide:
        calls = {getattr(d.call, "__qualname__", "") for d in r.dependant.dependencies}
        assert any("require_human_decider" in c for c in calls), r.path


def test_attestation_is_clamped_to_the_pause_and_strict_about_booleans():
    from datetime import datetime, timedelta, timezone
    from app.services.hitl_manager import normalize_attestation
    started = datetime.now(timezone.utc) - timedelta(seconds=10)
    att = normalize_attestation({"seconds_visible": 3600, "diff_shown": "false",
                                 "reasoning_shown": 1}, approver="a@example.com",
                                approved=True, pause_started_at=started.isoformat())
    assert att["overclaimed"] is True and att["seconds_visible"] <= 12
    assert att["diff_shown"] is False and att["reasoning_shown"] is False
    assert att["approver_kind"] == "human" and att["self_review"] is False
    own = normalize_attestation({"seconds_visible": 4}, approver="a@example.com",
                                approved=True, maker="a@example.com")
    assert own["self_review"] is True and own["overclaimed"] is False
