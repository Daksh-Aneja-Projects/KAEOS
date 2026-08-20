"""S6/M2.6 - the execution state machine has exactly ONE vocabulary.

The status strings were 190 bare literals across 64 files, and four modules kept
their own private copy of the constant set. That is how the autonomy governor
came to count `status IN ("SUCCESS_CLEAN", "SUCCESS")` while the north-star
metric counted `SUCCESS_CLEAN` alone - two definitions of the same number, one
of them matching a value the column cannot even hold.

These tests pin the vocabulary to the strings already in the database, and wire a
tripwire so the north-star consumers cannot silently re-diverge.
"""
import uuid

import pytest
from sqlalchemy import text

from app.models.domain import SkillExecution
from app.models.execution_status import (
    BLOCKED_STATUSES,
    FAILED_STATUSES,
    PENDING_STATUSES,
    SAFE_AUTONOMOUS_STATUSES,
    TERMINAL_STATUSES,
    AgentState,
    ExecutionStatus,
    is_safe_autonomous,
)

TENANT = "tenant_s6_exec_status"


# ── 1. The values ARE the strings the DB holds today ─────────────────────────

def test_execution_status_values_are_pinned():
    """Every member, pinned. A rename here is a silent data migration."""
    assert {s.name: s.value for s in ExecutionStatus} == {
        "SUCCESS_CLEAN": "SUCCESS_CLEAN",
        "SUCCESS_WITH_EDIT": "SUCCESS_WITH_EDIT",
        "HUMAN_OVERRIDDEN": "HUMAN_OVERRIDDEN",
        "PENDING_HITL": "PENDING_HITL",
        "ESCALATED_DEBATE": "ESCALATED_DEBATE",
        "BLOCKED_COMPLIANCE": "BLOCKED_COMPLIANCE",
        "BLOCKED_DEBATE": "BLOCKED_DEBATE",
        "BLOCKED_ACTUATION": "BLOCKED_ACTUATION",
        "BLOCKED_RATE_LIMIT": "BLOCKED_RATE_LIMIT",
        "FAILED": "FAILED",
        "FAILED_RULE_MISMATCH": "FAILED_RULE_MISMATCH",
        "FAILED_ACTUATION": "FAILED_ACTUATION",
        "FAILED_AUDIT": "FAILED_AUDIT",
        "FAILED_AUDIT_REVERSED": "FAILED_AUDIT_REVERSED",
        "FAILED_RESUME": "FAILED_RESUME",
    }


def test_agent_state_values_are_pinned():
    assert {s.name: s.value for s in AgentState} == {
        "IDLE": "IDLE",
        "RUNNING": "RUNNING",
        "PAUSED": "PAUSED",
        "PENDING_HITL": "PENDING_HITL",
        "BLOCKED": "BLOCKED",
        "COMPLETED": "COMPLETED",
        "FAILED": "FAILED",
    }


def test_members_are_indistinguishable_from_plain_strings():
    """StrEnum, not (str, Enum): `str()` and f-strings must yield the bare value.

    app.core.metrics.observe_pipeline does `str(status)` to build a Prometheus
    label, and runtime.py feeds it the raw pipeline status. Under a plain
    `(str, Enum)` that label would read "ExecutionStatus.SUCCESS_CLEAN" on
    Python 3.12+ and every alert keyed on status="SUCCESS_CLEAN" would go blind.
    """
    s = ExecutionStatus.SUCCESS_CLEAN
    assert s == "SUCCESS_CLEAN"
    assert str(s) == "SUCCESS_CLEAN"
    assert f"{s}" == "SUCCESS_CLEAN"
    assert "%s" % s == "SUCCESS_CLEAN"
    assert isinstance(s, str)
    # Dict/JSON round-trip: a member keys and serializes as its plain value.
    import json
    assert json.dumps({"status": s}) == '{"status": "SUCCESS_CLEAN"}'
    assert {"SUCCESS_CLEAN": 1}[s] == 1


def test_derived_sets_partition_the_vocabulary():
    assert SAFE_AUTONOMOUS_STATUSES == {ExecutionStatus.SUCCESS_CLEAN}
    assert PENDING_STATUSES.isdisjoint(TERMINAL_STATUSES)
    assert PENDING_STATUSES | TERMINAL_STATUSES == set(ExecutionStatus)
    assert SAFE_AUTONOMOUS_STATUSES <= TERMINAL_STATUSES
    assert BLOCKED_STATUSES.isdisjoint(FAILED_STATUSES)
    # safe_autonomy._classify_counts uses `status LIKE 'FAILED%'` as the SQL
    # spelling of FAILED_STATUSES. That is only equivalent while every failure
    # member is FAILED-prefixed and no non-failure member is.
    assert all(s.value.startswith("FAILED") for s in FAILED_STATUSES)
    assert all(s in FAILED_STATUSES
               for s in ExecutionStatus if s.value.startswith("FAILED"))


def test_step_vocabulary_is_not_the_execution_vocabulary():
    """The exact confusion that produced the governor divergence.

    SkillExecutor's per-step results use SUCCESS/FAILED/SKIPPED. Only "FAILED"
    overlaps, and it does so by coincidence, not by meaning.
    """
    assert "SUCCESS" not in set(ExecutionStatus)
    assert "SKIPPED" not in set(ExecutionStatus)
    assert not is_safe_autonomous(False, "SUCCESS")


# ── 2. The north-star tripwire ───────────────────────────────────────────────

def test_north_star_consumers_share_one_set_object():
    """The regression guard.

    Every consumer of the safe-autonomy rate must reference the SAME set object
    from app.models.execution_status - not a copy, not an equal-but-separate
    literal. `is` (not `==`) is the point: two modules that each build their own
    frozenset({SUCCESS_CLEAN}) compare equal today and drift apart tomorrow,
    which is exactly what happened.
    """
    from app.models import execution_status as canon
    from app.services import autonomy_governor, safe_autonomy, time_machine

    # The SQL consumers hold the set itself.
    assert safe_autonomy.SAFE_AUTONOMOUS_STATUSES is canon.SAFE_AUTONOMOUS_STATUSES
    assert autonomy_governor.SAFE_AUTONOMOUS_STATUSES is canon.SAFE_AUTONOMOUS_STATUSES
    # The Time Machine reconstructs the metric as-of a past moment via the
    # shared predicate rather than its own copy of the rule.
    assert time_machine._is_safe is canon.is_safe_autonomous


def test_north_star_consumers_agree_on_the_same_rows():
    """Behavioural half of the tripwire: identity is not enough, the predicate
    must actually classify identically for every status in the vocabulary."""
    from app.services.time_machine import _is_safe

    for status in ExecutionStatus:
        expected = status in SAFE_AUTONOMOUS_STATUSES
        assert _is_safe(False, status) is expected, status
        # A human gate disqualifies the run whatever the status.
        assert _is_safe(True, status) is False, status


def test_governor_no_longer_counts_the_phantom_success_status():
    """The documented divergence, pinned dead.

    app/services/autonomy_governor.py counted ("SUCCESS_CLEAN", "SUCCESS").
    Numerically inert (nothing writes bare "SUCCESS" to the column) but it made
    the governor's rate looser than the metric it governs.
    """
    from app.services.autonomy_governor import SAFE_AUTONOMOUS_STATUSES as gov_set

    assert "SUCCESS" not in gov_set
    assert gov_set == {ExecutionStatus.SUCCESS_CLEAN}


# ── 3. The DB stores plain strings ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_enum_round_trips_through_sqlalchemy_as_a_plain_string(db):
    """Write enum members, read back the RAW column: it must be bare strings.

    The whole refactor rests on this. If SQLAlchemy stored the repr, every
    existing row would stop matching and every metric would read zero.
    """
    exec_id = str(uuid.uuid4())
    db.add(SkillExecution(
        id=exec_id, tenant_id=TENANT, skill_id_name="s6_probe",
        status=ExecutionStatus.SUCCESS_CLEAN,
        outcome_type=ExecutionStatus.SUCCESS_WITH_EDIT,
        agent_state=AgentState.COMPLETED,
        route_type="SKILL_EXEC", duration_ms=1, hitl_required=False,
    ))
    await db.commit()

    # Raw SQL, bypassing the ORM entirely - no chance of a Python-side coercion
    # hiding a bad stored value.
    row = (await db.execute(text(
        "SELECT status, outcome_type, agent_state FROM skill_executions WHERE id = :i"
    ), {"i": exec_id})).one()
    assert row[0] == "SUCCESS_CLEAN"
    assert row[1] == "SUCCESS_WITH_EDIT"
    assert row[2] == "COMPLETED"
    assert [type(v) for v in row] == [str, str, str]


@pytest.mark.asyncio
async def test_enum_members_match_rows_written_as_plain_strings(db):
    """The reverse direction: a legacy row written as a bare literal must still
    be found by a query built from the enum, including via IN()."""
    from sqlalchemy import select

    exec_id = str(uuid.uuid4())
    db.add(SkillExecution(
        id=exec_id, tenant_id=TENANT, skill_id_name="s6_legacy",
        status="SUCCESS_CLEAN",  # deliberately the bare literal
        route_type="SKILL_EXEC", duration_ms=1, hitl_required=False,
    ))
    await db.commit()

    found = (await db.execute(
        select(SkillExecution.id).where(
            SkillExecution.tenant_id == TENANT,
            SkillExecution.id == exec_id,
            # frozenset of enum members into IN() - the form _classify_counts uses
            SkillExecution.status.in_(SAFE_AUTONOMOUS_STATUSES),
        )
    )).scalar_one_or_none()
    assert found == exec_id


@pytest.mark.asyncio
async def test_canonical_metric_counts_enum_written_rows(db):
    """End-to-end: rows written with enum members are counted by the north-star
    query exactly as literal-written rows were."""
    from app.services.safe_autonomy import compute_safe_autonomy

    tenant = "tenant_s6_metric"
    rows = [
        (ExecutionStatus.SUCCESS_CLEAN, False),        # safe autonomous
        (ExecutionStatus.SUCCESS_CLEAN, True),         # a human gated it
        (ExecutionStatus.FAILED_RULE_MISMATCH, False),  # unattended failure
    ]
    for status, hitl in rows:
        db.add(SkillExecution(
            id=str(uuid.uuid4()), tenant_id=tenant, skill_id_name="s6_metric",
            status=status, outcome_type=status, route_type="SKILL_EXEC",
            duration_ms=1, hitl_required=hitl,
        ))
    await db.commit()

    sar = await compute_safe_autonomy(db, tenant, days=3650)
    assert sar["total_executions"] == 3
    assert sar["safe_autonomous"] == 1
    assert sar["safe_autonomy_rate"] == pytest.approx(1 / 3, abs=1e-4)
    assert sar["fallout"]["failed"] == 1
    assert sar["fallout"]["routed_to_human"] == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
