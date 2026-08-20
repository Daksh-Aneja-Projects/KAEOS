"""Canonical vocabulary for the governed-execution state machine.

``SkillExecution`` carries three status-ish columns and they are NOT one
vocabulary:

* ``status`` / ``outcome_type`` share ONE vocabulary (:class:`ExecutionStatus`).
  ``outcome_type`` is the status the run *ended up with* - the executor copies
  ``status`` into it verbatim, except that an approve-with-edit is downgraded to
  ``SUCCESS_WITH_EDIT`` (see ``SkillExecutor._persist_execution``). So
  ``outcome_type`` is a subset of the same enum, not a second one.
* ``agent_state`` is a genuinely different vocabulary (:class:`AgentState`) -
  the run's lifecycle position, not its governance verdict. ``PENDING_HITL``
  is deliberately a member of BOTH; a paused run is pending in both senses.

Both are ``StrEnum`` (not ``class X(str, Enum)``) on purpose. A ``StrEnum``
member IS a ``str``, so it compares equal to the plain literal, serializes to
JSON as the bare string, and binds into a SQLAlchemy ``String`` column as the
bare string - AND ``str(member)`` / ``f"{member}"`` also render the bare value.
Plain ``(str, Enum)`` renders ``"ExecutionStatus.SUCCESS_CLEAN"`` from ``str()``
on Python 3.12+, which would have silently poisoned the Prometheus label in
``app.core.metrics.observe_pipeline`` (it does ``str(status)``) and every
logging f-string. The values below are exactly the strings already in the DB.

THE NORTH STAR lives here too. See :data:`SAFE_AUTONOMOUS_STATUSES`.
"""
from __future__ import annotations

from enum import StrEnum
from typing import Optional


class ExecutionStatus(StrEnum):
    """Governance verdict of one execution (``SkillExecution.status`` and
    ``.outcome_type``). Every member is a string this system already writes."""

    # -- Completed ---------------------------------------------------------
    SUCCESS_CLEAN = "SUCCESS_CLEAN"
    #: Completed, but a human corrected the answer. Written to ``outcome_type``
    #: by the executor (and to ``status`` by the demo seed). NOT safe autonomy.
    SUCCESS_WITH_EDIT = "SUCCESS_WITH_EDIT"
    #: A human rejected/replaced the agent's decision.
    HUMAN_OVERRIDDEN = "HUMAN_OVERRIDDEN"

    # -- Awaiting a human (non-terminal) -----------------------------------
    PENDING_HITL = "PENDING_HITL"
    ESCALATED_DEBATE = "ESCALATED_DEBATE"

    # -- Refused by a gate before acting -----------------------------------
    BLOCKED_COMPLIANCE = "BLOCKED_COMPLIANCE"
    BLOCKED_DEBATE = "BLOCKED_DEBATE"
    BLOCKED_ACTUATION = "BLOCKED_ACTUATION"
    BLOCKED_RATE_LIMIT = "BLOCKED_RATE_LIMIT"

    # -- Tried and failed --------------------------------------------------
    #: Defensive fallback only: ``HITLManager.resume_execution`` writes
    #: ``result.get("status", "FAILED")``, so an engine result missing its
    #: status key lands here. Not a verdict any gate produces deliberately.
    FAILED = "FAILED"
    FAILED_RULE_MISMATCH = "FAILED_RULE_MISMATCH"
    FAILED_ACTUATION = "FAILED_ACTUATION"
    FAILED_AUDIT = "FAILED_AUDIT"
    FAILED_AUDIT_REVERSED = "FAILED_AUDIT_REVERSED"
    FAILED_RESUME = "FAILED_RESUME"


class AgentState(StrEnum):
    """Lifecycle position of one execution (``SkillExecution.agent_state``)."""

    IDLE = "IDLE"          # column default
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    PENDING_HITL = "PENDING_HITL"
    BLOCKED = "BLOCKED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


# ── Derived sets ─────────────────────────────────────────────────────────────

#: THE NORTH-STAR NUMERATOR. An execution counts toward the safe-autonomy rate
#: when ``hitl_required IS FALSE`` (no human gate) AND ``status`` is in this set.
#: Use :func:`is_safe_autonomous` rather than re-deriving the rule.
#:
#: CANONICAL DEFINITION, per README ("the share of work completed without human
#: intervention, at a quality bar"), docs/FEATURES.md, and the shipped
#: regression tests/test_safe_autonomy_consistency.py: clean completion ONLY.
#: An edit, an override, a block or a failure all fall OUT of the numerator and
#: are reported as named fallout instead.
#:
#: DIVERGENCE THIS REPLACES: app/services/autonomy_governor.py counted
#: ``status IN ("SUCCESS_CLEAN", "SUCCESS")``. Bare ``"SUCCESS"`` belongs to the
#: per-STEP result vocabulary (``SkillExecutor._execute_step``), never to
#: ``SkillExecution.status`` - so the governor was matching a value this column
#: cannot hold. Numerically inert today, but it would have inflated the
#: governor's rate (and relaxed autonomy dials) the moment any writer started
#: stamping the step vocabulary onto an execution row.
SAFE_AUTONOMOUS_STATUSES: frozenset[ExecutionStatus] = frozenset({
    ExecutionStatus.SUCCESS_CLEAN,
})

#: The agent's answer STOOD - it completed, with or without a human correcting
#: it afterwards. Deliberately wider than :data:`SAFE_AUTONOMOUS_STATUSES`,
#: which is the north star and additionally requires that no human was involved
#: at all. Use this one for "did the work get delivered / did this run succeed",
#: never for the autonomy rate.
#:
#: HUMAN_OVERRIDDEN is OUT: a human replaced the decision, so the agent's answer
#: did not stand. This set replaces two hand-rolled string tests
#: (``status.startswith("SUCCESS")`` in the genome traits and ``"SUCCESS" in
#: status`` in the predictive feature build) that matched these same two members
#: by accident of spelling - and would have silently absorbed any future member
#: that happened to start with, or merely contain, the word SUCCESS.
SUCCEEDED_STATUSES: frozenset[ExecutionStatus] = frozenset({
    ExecutionStatus.SUCCESS_CLEAN,
    ExecutionStatus.SUCCESS_WITH_EDIT,
})

#: Waiting on a human; the run is not finished and must not be counted as
#: either a success or a failure.
PENDING_STATUSES: frozenset[ExecutionStatus] = frozenset({
    ExecutionStatus.PENDING_HITL,
    ExecutionStatus.ESCALATED_DEBATE,
})

#: A gate refused to let the run act. Distinct from FAILED: nothing was tried.
BLOCKED_STATUSES: frozenset[ExecutionStatus] = frozenset({
    ExecutionStatus.BLOCKED_COMPLIANCE,
    ExecutionStatus.BLOCKED_DEBATE,
    ExecutionStatus.BLOCKED_ACTUATION,
    ExecutionStatus.BLOCKED_RATE_LIMIT,
})

#: The run acted (or tried to) and did not succeed. Every member starts with
#: ``FAILED``, which is why the SQL fallout counters can stay on the cheaper
#: ``status LIKE 'FAILED%'`` and still mean exactly this set.
FAILED_STATUSES: frozenset[ExecutionStatus] = frozenset({
    ExecutionStatus.FAILED,
    ExecutionStatus.FAILED_RULE_MISMATCH,
    ExecutionStatus.FAILED_ACTUATION,
    ExecutionStatus.FAILED_AUDIT,
    ExecutionStatus.FAILED_AUDIT_REVERSED,
    ExecutionStatus.FAILED_RESUME,
})

#: Reached an end state - nothing further will happen without a new run.
TERMINAL_STATUSES: frozenset[ExecutionStatus] = frozenset(
    set(ExecutionStatus) - PENDING_STATUSES
)


def is_safe_autonomous(hitl_required: Optional[bool], status: Optional[str]) -> bool:
    """The north-star predicate: ran with no human gate AND completed cleanly.

    The single in-Python definition. The SQL form lives in
    ``app.services.safe_autonomy._classify_counts`` and reads the same set.
    """
    return (not hitl_required) and (status in SAFE_AUTONOMOUS_STATUSES)


if __name__ == "__main__":
    # Self-check: the enum must behave as the plain strings the DB holds.
    assert ExecutionStatus.SUCCESS_CLEAN == "SUCCESS_CLEAN"
    assert str(ExecutionStatus.SUCCESS_CLEAN) == "SUCCESS_CLEAN"
    assert f"{ExecutionStatus.SUCCESS_CLEAN}" == "SUCCESS_CLEAN"
    assert is_safe_autonomous(False, "SUCCESS_CLEAN")
    assert not is_safe_autonomous(True, "SUCCESS_CLEAN")
    assert not is_safe_autonomous(False, "FAILED_RULE_MISMATCH")
    assert not is_safe_autonomous(False, "SUCCESS")  # step vocabulary, not ours
    assert ExecutionStatus.PENDING_HITL not in TERMINAL_STATUSES
    # SUCCEEDED is the old startswith("SUCCESS") test, made explicit: exactly the
    # members that spelling used to catch, and nothing else.
    assert SUCCEEDED_STATUSES == {m for m in ExecutionStatus if m.startswith("SUCCESS")}
    assert ExecutionStatus.HUMAN_OVERRIDDEN not in SUCCEEDED_STATUSES
    assert SAFE_AUTONOMOUS_STATUSES < SUCCEEDED_STATUSES
    assert ExecutionStatus.FAILED_RESUME in TERMINAL_STATUSES
    print("execution_status self-check OK")
