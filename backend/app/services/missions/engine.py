"""Mission engine — governed execution of a mission's DAG.

Runs dependency-ready steps in order. Each executable step runs its real skill
through the full 7-gate ``AgentExecutor`` (never a shortcut around governance).
A budget gate stops the mission before an over-budget step; a HITL checkpoint
pauses it for human approval; every transition is appended to the mission ledger.
The engine is re-entrant: call ``advance_mission`` again after a human approves a
checkpoint or lifts the budget, and it picks up exactly where it paused.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rls import is_postgres
from app.models.domain import Skill
from app.models.execution_status import ExecutionStatus, PENDING_STATUSES
from app.models.missions import Mission, MissionStep, MissionEvent
from app.services import prompt_guard

logger = logging.getLogger(__name__)

_TERMINAL_STEP = {"DONE", "FAILED", "SKIPPED"}

# Missions currently being driven by a background task in THIS process. Guards
# against two concurrent runners for the same mission. (Best-effort, in-process;
# a stale RUNNING step from a crashed worker is recovered by _recover_stale below.)
_RUNNING_MISSIONS: set[str] = set()
_STEP_STALE_AFTER = timedelta(minutes=10)   # a RUNNING step older than this is presumed crashed


async def start_mission_run(tenant_id: str, mission_id: str) -> None:
    """Kick off (or resume) a background runner that advances the mission until it
    completes or pauses (HITL / budget). Non-blocking and idempotent: a mission
    already running in this process is a no-op, so the API returns instantly and
    the UI polls GET /missions/{id} for progress."""
    if mission_id in _RUNNING_MISSIONS:
        return
    _RUNNING_MISSIONS.add(mission_id)
    asyncio.create_task(_run_bg(tenant_id, mission_id))


async def _run_bg(tenant_id: str, mission_id: str) -> None:
    from app.core.database import AsyncSessionLocal
    try:
        for _ in range(200):   # hard bound; a real mission pauses/completes far sooner
            async with AsyncSessionLocal() as db:
                res = await advance_mission(db, tenant_id=tenant_id, mission_id=mission_id)
            if res.get("status") != "RUNNING":
                break
    except Exception as e:                     # pragma: no cover - background safety net
        logger.warning(f"[mission] background runner for {mission_id} stopped: {e}")
    finally:
        _RUNNING_MISSIONS.discard(mission_id)


async def _load(db: AsyncSession, tenant_id: str, mission_id: str):
    mission = (await db.execute(
        select(Mission).where(Mission.id == mission_id, Mission.tenant_id == tenant_id)
    )).scalar_one_or_none()
    if mission is None:
        return None, []
    steps = (await db.execute(
        select(MissionStep).where(
            MissionStep.mission_id == mission_id, MissionStep.tenant_id == tenant_id)
        .order_by(MissionStep.seq)
    )).scalars().all()
    return mission, steps


def _event(db, mission, kind, message, step_seq=None):
    db.add(MissionEvent(tenant_id=mission.tenant_id, mission_id=mission.id,
                        kind=kind, message=message, step_seq=step_seq))


def _deps_ready(step: MissionStep, by_seq: dict[int, MissionStep]) -> bool:
    for d in step.depends_on or []:
        dep = by_seq.get(d)
        if dep is None or dep.status not in ("DONE", "SKIPPED"):
            return False
    return True


async def _execute_step(db: AsyncSession, mission: Mission, step: MissionStep,
                        execution_id: str) -> dict:
    """Run the step as a GOVERNED ADVISORY action through the AgentExecutor.

    A mission is goal-level *orchestration*: each step reasons, under the real
    department's governance profile (its confidence drives the HITL gate), about
    the recommended action toward the goal — it does not fire the department's
    transactional contract, which needs concrete entity inputs a goal rarely
    carries (doing so would just fail rule-matching or the audit gate). The
    advisory recommendation still passes the 7 gates (compliance, fairness,
    confidence/HITL, debate, execute, audit); transactional compliance and the
    actual write-back happen at ACTUATION time (Phase 1) with real data. This
    keeps missions honest AND working on a live model.

    Must NOT mutate `step` here — a dirty session would, on SQLite, deadlock the
    executor's own-session writes. The engine persists step state around this call.
    """
    skill = (await db.execute(
        select(Skill).where(Skill.skill_id == step.skill_id, Skill.tenant_id == mission.tenant_id)
    )).scalar_one_or_none()
    # End the read transaction the Skill lookup opened, releasing this session's
    # pooled connection for the minutes the gate pipeline below can take (M6.1).
    # The engine committed all step/mission state before calling here, so this
    # commits nothing but the read; expire_on_commit=False keeps `skill` live.
    await db.commit()

    if skill is None:
        return {"status": "FAILED", "reason": f"skill {step.skill_id} not found"}

    # ── HITL approval guard ──────────────────────────────────────────────
    # A HITL-gated step may only execute on the strength of its PERSISTED
    # approval record (approver identity + timestamp, written exclusively by
    # resolve_hitl_step). step.hitl_required is a requirement, not evidence an
    # approval occurred; deriving pre-approval from it would silently disable
    # Gate 3 on exactly the steps that most need it if the status invariant
    # ever broke. No record -> the step never executes; it re-gates to HITL.
    step_approved = bool(step.approved_by and step.approved_at)
    if step.hitl_required and not step_approved:
        logger.error(
            f"[mission] step {step.seq} is hitl_required with no approval record; "
            "refusing to execute and re-gating to HITL."
        )
        return {"status": "PENDING_HITL",
                "reason": "HITL-gated step has no persisted approval record"}

    from app.agents.runtime import AgentExecutor
    from app.services.compliance import ComplianceEngine
    from app.services.hitl_manager import hitl_manager

    dept = (skill.department or skill.domain or "general")
    # A single generative advisory step the model completes with a recommendation.
    advisory_step = {
        "id": "recommend",
        "name": f"recommend_{dept}_action",
        "prompt": (
            # mission.goal is operator/signal-authored text. Fence it as data so a
            # goal carrying "ignore your instructions..." cannot re-steer the agent.
            f"Mission goal:\n{prompt_guard.wrap_untrusted(mission.goal)}\n"
            f"You are the {dept} function using the '{skill.skill_id}' capability. "
            f"Recommend the single best {dept} action toward this goal. "
            "Respond ONLY as JSON: "
            '{"decision": "<the recommended action>", "rationale": "<one sentence>", '
            '"risks": ["<risk>"], "status": "SUCCESS", "confidence": 0.0}'
        ),
        "tool": "none",
    }
    # Advisory planning processes no transaction and no personal data, so the
    # transactional audit tags (SOX amount, GDPR lawful basis) do not apply to the
    # recommendation itself. The governed WRITE-BACK is a different matter: runtime
    # Gate 5b re-gates any actuation against the skill's own statutory checkers
    # (SOX four-eyes, ECOA, ...) before it lands, so an untagged advisory step
    # cannot smuggle a write past compliance. Fairness still engages for
    # people-facing recommendations.
    people_facing = dept.lower() in ("hr", "human_resources", "people", "workforce", "recruiting")
    skill_dict = {
        "skill_id": skill.skill_id,
        "department": dept,
        "steps": [advisory_step],
        "compliance_tags": ["EEOC"] if people_facing else [],
        "confidence": skill.confidence or 0.0,
    }
    # L7 closed loop: a HUMAN-APPROVED step carrying a concrete actuation intent
    # graduates from advice to a governed WRITE. The intent rides on skill_dict so
    # runtime Gate 5b (which only fires when it sees `actuation`) performs the
    # idempotent, reversible write-back AFTER every gate has passed. Advisory-only
    # steps (no intent, or not human-approved) behave exactly as before.
    step_actuation = getattr(step, "actuation", None)
    if step_approved and isinstance(step_actuation, dict) and step_actuation:
        skill_dict["actuation"] = step_actuation
    ctx = {
        "tenant_id": mission.tenant_id,
        "execution_id": execution_id,
        "mission_id": mission.id,
        "mission_step_seq": step.seq,
        "task_intent": f"[mission] {mission.goal} :: {step.name}",
        "_skill_obj": skill,
        "requires_fairness_assessment": people_facing,
        # Derived from the persisted approval record (guard above), never from
        # hitl_required: the flag carries the real approver identity so the
        # downstream SOX check attributes the action to an actual human.
        "has_human_approver": step.approved_by if step_approved else False,
        # Four-eyes (SoD): the mission's initiator is the MAKER, the step's human
        # approver is the APPROVER. check_sox blocks when they are the same
        # identity, so a governed financial write-back cannot be both created and
        # approved by one person. mission.created_by may be a human, "event-mesh",
        # or None (a None maker fails four-eyes closed at Gate 5b).
        "maker": mission.created_by,
        "approver": step.approved_by if step_approved else None,
    }
    executor = AgentExecutor(ComplianceEngine(), hitl_manager)
    try:
        # Gate 3 pre-approval rides on an explicit keyword argument (not the
        # context dict) so request-controlled data can never smuggle it in.
        return await executor.execute_skill(skill_dict, ctx, hitl_pre_approved=step_approved)
    except Exception as e:
        logger.warning(f"[mission] step {step.seq} execution error: {e}")
        return {"status": "FAILED", "reason": str(e)}


def _recommendation_of(result: dict) -> Optional[str]:
    """Pull the model's recommendation text out of the executor result chain."""
    from app.services.json_utils import extract_json_object
    chain = result.get("reasoning_chain") or []
    if not chain:
        return None
    last = chain[-1] if isinstance(chain[-1], dict) else {}
    # The advisory step returns JSON with a "decision"; fall back to raw output.
    for key in ("decision", "output"):
        val = last.get(key)
        if isinstance(val, str) and val.strip():
            txt = val.strip()
            if txt.startswith("{"):
                try:
                    parsed = extract_json_object(txt)
                    if parsed.get("decision"):
                        return str(parsed["decision"])[:240]
                except ValueError:
                    # Display-only summary extraction. Unparseable model output
                    # falls through to the raw truncated text below; it never
                    # affects the step's governed outcome.
                    pass
            return txt[:240]
    return None


def _cost_of(result: dict) -> Decimal:
    """Executor cost as an exact Decimal. via str() so a float like 0.1 becomes
    Decimal('0.1'), not its binary-noise expansion, before it enters the ledger."""
    c = result.get("cost")
    if isinstance(c, dict):
        c = c.get("total_usd") or c.get("usd") or 0
    if isinstance(c, Decimal):
        return c
    if isinstance(c, (int, float)):
        return Decimal(str(c))
    return Decimal("0")


def _finalize(db, mission, steps) -> None:
    """Set the mission's terminal/paused status from its steps."""
    if any(s.status == "AWAITING_HITL" for s in steps):
        # Notify only on the TRANSITION into the paused state, not on every
        # advance while already paused - the approver needs one ping, not spam.
        if mission.status != "AWAITING_HITL":
            waiting = [s for s in steps if s.status == "AWAITING_HITL"]
            from app.services.notifier import notify_fire_and_forget
            notify_fire_and_forget(
                mission.tenant_id, "mission.checkpoint",
                subject=f"KAEOS mission checkpoint: {(mission.goal or '')[:60]}",
                body=(f"Mission paused at an approval checkpoint.\n"
                      f"Goal: {mission.goal}\n"
                      f"Steps awaiting approval: "
                      f"{', '.join(f'{s.seq}:{s.skill_id or s.department}' for s in waiting[:5])}\n"
                      f"Review it in KAEOS Mission Control."),
                data={"mission_id": mission.id,
                      "steps": [s.seq for s in waiting]},
            )
        mission.status = "AWAITING_HITL"
        return
    if all(s.status in _TERMINAL_STEP for s in steps) and steps:
        done = sum(1 for s in steps if s.status == "DONE")
        failed = sum(1 for s in steps if s.status == "FAILED")
        skipped = sum(1 for s in steps if s.status == "SKIPPED")
        if done and (failed or skipped):
            mission.status = "COMPLETED_WITH_EXCEPTIONS"
        elif done:
            mission.status = "COMPLETED"
        elif failed:
            mission.status = "FAILED"
        else:
            mission.status = "ABORTED"
        mission.completed_at = datetime.now(timezone.utc)
        _event(db, mission, "COMPLETED",
               f"Mission finished ({mission.status}): {done} done, {failed} failed, {skipped} skipped.")


_TERMINAL_MISSION = {"COMPLETED", "COMPLETED_WITH_EXCEPTIONS", "FAILED", "ABORTED"}


async def _writeback_signal_on_finish(db: AsyncSession, mission) -> None:
    """L4 closed loop: when an event-mesh-spawned mission finishes, write its
    terminal status back to the originating signal and record OutcomeRecords
    (which feed the L1 outcome-learning loop). Idempotent + non-fatal.

    Outcomes are attributed to the mission's REAL step executions - the same
    execution ids the skill_executions table carries - so each record joins back
    to the decision it judges and rolls up under the skill that made it. The old
    surrogate (execution_id=mission.id, skill_id_name="mission:<uuid>") joined to
    nothing and invented a one-row "skill" per mission in the per-skill stats.
    """
    if mission.created_by != "event-mesh" or mission.status not in _TERMINAL_MISSION:
        return
    try:
        from app.models.event_mesh import ExternalSignal
        from app.models.intelligence_metrics import OutcomeRecord
        sig = (await db.execute(
            select(ExternalSignal).where(
                ExternalSignal.tenant_id == mission.tenant_id,
                ExternalSignal.response_ref == mission.id,
            )
        )).scalar_one_or_none()
        if sig is None or sig.status == "RESOLVED":
            return  # nothing to close, or already closed (idempotent)
        sig.status = "RESOLVED"
        good = mission.status in ("COMPLETED", "COMPLETED_WITH_EXCEPTIONS")

        steps = (await db.execute(
            select(MissionStep).where(
                MissionStep.mission_id == mission.id,
                MissionStep.tenant_id == mission.tenant_id,
            )
        )).scalars().all()
        executed = [s for s in steps if s.execution_id and s.status in ("DONE", "FAILED")]

        if executed:
            for s in executed:
                db.add(OutcomeRecord(
                    tenant_id=mission.tenant_id,
                    execution_id=s.execution_id,      # the real SkillExecution id
                    skill_id_name=s.skill_id,
                    outcome="GOOD" if s.status == "DONE" else "BAD",
                    autonomous=not bool(s.hitl_required),
                    note=f"event-mesh mission {mission.id} {mission.status}",
                ))
        else:
            # The mission finished without executing a single skill (aborted,
            # all-skipped, budget-blocked at step 1). The signal outcome is still
            # worth recording, but there is no skill to credit or blame: the NULL
            # skill name keeps it out of the per-skill rollup in /outcomes/impact.
            db.add(OutcomeRecord(
                tenant_id=mission.tenant_id,
                execution_id=mission.id,
                skill_id_name=None,
                outcome="GOOD" if good else "BAD",
                autonomous=True,
                note=f"event-mesh mission {mission.status} (no step executed)",
            ))
    except Exception as e:
        # Non-fatal (a mission must still finish), but this is a broken learning
        # loop, not a detail: name the signal so it can be reconciled by hand.
        logger.error(
            f"[mission] L4 signal writeback FAILED for mission {mission.id} "
            f"(signal response_ref={mission.id}): {e}"
        )


async def advance_mission(db: AsyncSession, *, tenant_id: str, mission_id: str) -> dict:
    """Advance the mission by ONE executable step, then return.

    One step per call keeps each request bounded (a single gated execution can take
    a while on a real model) and lets the UI stream progress by calling again.
    Steps are independent unless a dependency is declared, so an autonomous step
    still runs even while another awaits a human; a failed step is flagged as an
    exception, never a mission-wide crash.
    """
    mission, steps = await _load(db, tenant_id, mission_id)
    if mission is None:
        return {"error": "mission not found"}
    if mission.status in ("COMPLETED", "COMPLETED_WITH_EXCEPTIONS", "FAILED", "ABORTED"):
        return _summary(mission, steps)

    # Crash recovery: a step left RUNNING by a worker that died (its background task
    # never finished) would wedge the mission. Reset a stale RUNNING step so it can
    # be re-attempted (execution is idempotent at the governance layer).
    now = datetime.now(timezone.utc)
    for s in steps:
        if s.status == "RUNNING" and s.started_at:
            started = s.started_at if s.started_at.tzinfo else s.started_at.replace(tzinfo=timezone.utc)
            if now - started > _STEP_STALE_AFTER:
                s.status = "READY" if s.hitl_required else "PENDING"
                _event(db, mission, "STEP_FAILED",
                       f"Step {s.seq} was stale (worker crash); re-queued.", s.seq)
        elif s.status == "RUNNING":
            # A step is actively RUNNING in another task — do not double-execute.
            await db.commit()
            return _summary(mission, steps)

    by_seq = {s.seq: s for s in steps}

    # Pick one executable step: dependencies satisfied and either autonomous or a
    # human-approved (READY) checkpoint. Pending-HITL steps are skipped here.
    executable = None
    for s in steps:
        if s.status in _TERMINAL_STEP or s.status == "RUNNING":
            continue
        if not _deps_ready(s, by_seq):
            continue
        if s.hitl_required and s.status != "READY":
            continue
        executable = s
        break

    if executable is not None:
        # Budget gate BEFORE spending on this step.
        if mission.budget_usd is not None and mission.spent_usd >= mission.budget_usd:
            mission.status = "BUDGET_BLOCKED"
            _event(db, mission, "BUDGET_BLOCK",
                   f"Budget ${mission.budget_usd:.2f} reached (${mission.spent_usd:.2f} spent); "
                   f"step {executable.seq} held.", executable.seq)
            await db.commit()
            await db.refresh(mission)
            return _summary(mission, steps)

        # Atomic step claim: two replicas both _load this PENDING/READY step and
        # would both execute it (double governed run, double spent_usd, a Gate-5b
        # actuation like a vendor payment fired twice). On Postgres, lock the exact
        # row FOR UPDATE SKIP LOCKED, then re-check status: a concurrent worker
        # holding the lock is skipped, and one that already flipped it to RUNNING
        # fails the status predicate. On SQLite (single writer, single process) the
        # in-process _RUNNING_MISSIONS guard + the RUNNING early-return above is the
        # claim; there is no second replica to race.
        prior_status = executable.status
        if is_postgres(db):
            won = (await db.execute(
                select(MissionStep.id).where(
                    MissionStep.id == executable.id,
                    MissionStep.status == prior_status,
                ).with_for_update(skip_locked=True)
            )).scalar_one_or_none()
            if won is None:
                # Another replica claimed this step; do nothing this pass and let
                # the runner loop re-pick. Roll back so we hold no lock/tx.
                await db.rollback()
                return _summary(mission, steps)

        # Persist RUNNING + execution id and COMMIT before executing, so this
        # session holds no write tx / dirty row while the executor writes from its
        # own session (on SQLite that would deadlock as "database is locked").
        execution_id = f"mission-{mission.id[:8]}-s{executable.seq}-{uuid.uuid4().hex[:6]}"
        executable.status = "RUNNING"
        executable.started_at = datetime.now(timezone.utc)
        executable.execution_id = execution_id
        mission.status = "RUNNING"
        await db.commit()

        result = await _execute_step(db, mission, executable, execution_id)
        _apply_step_result(db, mission, executable, result)
        _finalize(db, mission, steps)
        await _writeback_signal_on_finish(db, mission)
        await db.commit()
        await db.refresh(mission)
        return _summary(mission, steps)

    # Nothing executable right now: surface any pending-HITL checkpoints.
    for s in steps:
        if s.status == "PENDING" and s.hitl_required and _deps_ready(s, by_seq):
            s.status = "AWAITING_HITL"
            _event(db, mission, "HITL_PAUSE",
                   f"Step {s.seq} ({s.name}) awaits human approval.", s.seq)
    _finalize(db, mission, steps)
    await _writeback_signal_on_finish(db, mission)
    await db.commit()
    await db.refresh(mission)
    return _summary(mission, steps)


def _apply_step_result(db, mission, step, result: dict) -> None:
    """Fold one executor result into the step + mission (no commit)."""
    status = result.get("status")
    cost = _cost_of(result)
    step.cost_usd = cost
    mission.spent_usd = (mission.spent_usd or Decimal("0")) + cost
    if status == ExecutionStatus.SUCCESS_CLEAN:
        step.status = "DONE"
        step.completed_at = datetime.now(timezone.utc)
        step.result_summary = _recommendation_of(result) or \
            f"{result.get('steps_completed', 0)} steps, {result.get('duration_ms', 0)}ms"
        _event(db, mission, "STEP_DONE",
               f"Step {step.seq} ({step.name}): {step.result_summary}", step.seq)
    # Every way a run can end up waiting on a person lands here: PENDING_STATUSES
    # (the confidence gate's PENDING_HITL and the debate arbitrator's
    # ESCALATED_DEBATE) plus hitl_manager's own words for the same thing
    # ("PENDING" / "HITL_REQUIRED" / pending=True), which are not execution-
    # vocabulary values. ESCALATED_DEBATE used to fall through to the FAILED
    # branch below - that both lied about the outcome and kept the decision out
    # of the approval queue entirely.
    elif (status in PENDING_STATUSES or status in ("HITL_REQUIRED", "PENDING")
          or result.get("pending")):
        # Record the requirement on the step, not just the pause: the runner only
        # skips a paused step when hitl_required is set, so leaving it False lets
        # the next advance re-run the step instead of waiting for the human.
        step.hitl_required = True
        step.status = "AWAITING_HITL"
        why = ("two agents disagreed and the arbitrator sent it to a human"
               if status == ExecutionStatus.ESCALATED_DEBATE
               else "the confidence gate routed it to a human")
        _event(db, mission, "HITL_PAUSE",
               f"Step {step.seq} ({step.name}) is waiting for approval: {why}.", step.seq)
    elif status == ExecutionStatus.BLOCKED_COMPLIANCE and not step.hitl_required:
        # An autonomous action the compliance gate blocked ESCALATES to a human;
        # on approval it re-runs carrying the human-approver flag.
        step.hitl_required = True
        step.status = "AWAITING_HITL"
        reason = "; ".join(v.get("reason", "") for v in (result.get("violations") or [])) or "compliance block"
        _event(db, mission, "HITL_PAUSE",
               f"Step {step.seq} blocked by compliance ({reason}); escalated to human.", step.seq)
    else:
        # A genuine failure (blocked-after-approval, failed audit, execution error)
        # flags this step as an exception; independent steps still run.
        step.status = "FAILED"
        step.completed_at = datetime.now(timezone.utc)
        step.result_summary = result.get("reason") or status or "failed"
        _event(db, mission, "STEP_FAILED",
               f"Step {step.seq} ({step.name}) failed: {step.result_summary}", step.seq)


async def resolve_hitl_step(
    db: AsyncSession, *, tenant_id: str, mission_id: str, seq: int,
    approved: bool, approver: Optional[str] = None,
) -> dict:
    """Approve or reject a mission's HITL checkpoint, then resume (on approve)."""
    mission, steps = await _load(db, tenant_id, mission_id)
    if mission is None:
        return {"error": "mission not found"}
    step = next((s for s in steps if s.seq == seq), None)
    if step is None:
        return {"error": "step not found"}
    if step.status != "AWAITING_HITL":
        return {"error": f"step {seq} is {step.status}, not awaiting approval"}

    if approved:
        step.status = "READY"  # cleared checkpoint; the runner will execute it
        # The persisted approval record: the ONLY thing that lets a HITL-gated
        # step execute (see the guard in _execute_step).
        step.approved_by = approver or "human"
        step.approved_at = datetime.now(timezone.utc)
        mission.status = "RUNNING"
        _event(db, mission, "STARTED",
               f"Step {seq} approved by {approver or 'human'}; resuming.", seq)
        await db.commit()
        await db.refresh(mission)
        # NOTE: the caller (route) resumes execution via start_mission_run so the
        # engine stays synchronously testable and the async spawn lives at the edge.
        return _summary(mission, steps)
    else:
        step.status = "SKIPPED"
        step.result_summary = f"Rejected by {approver or 'human'}"
        _event(db, mission, "STEP_FAILED",
               f"Step {seq} ({step.name}) rejected by {approver or 'human'}; skipped.", seq)
        # Any step that declared a dependency on the rejected one is transitively
        # skipped; independent steps continue.
        by_seq = {s.seq: s for s in steps}
        changed = True
        while changed:
            changed = False
            for s in steps:
                if s.status in _TERMINAL_STEP:
                    continue
                if any((by_seq.get(d) and by_seq[d].status == "SKIPPED") for d in (s.depends_on or [])):
                    s.status = "SKIPPED"
                    s.result_summary = "Skipped: prerequisite step was rejected"
                    changed = True
        _finalize(db, mission, steps)
        await db.commit()
        await db.refresh(mission)
        return _summary(mission, steps)


async def abort_mission(db: AsyncSession, *, tenant_id: str, mission_id: str,
                        actor: Optional[str] = None) -> dict:
    """Human abort: stop the mission and reverse any actuations it caused."""
    mission, steps = await _load(db, tenant_id, mission_id)
    if mission is None:
        return {"error": "mission not found"}
    if mission.status in ("COMPLETED", "FAILED", "ABORTED"):
        return _summary(mission, steps)

    reversed_count = await _reverse_mission_actions(db, mission, steps)
    for s in steps:
        if s.status not in _TERMINAL_STEP:
            s.status = "SKIPPED"
            s.result_summary = "Skipped: mission aborted"
    mission.status = "ABORTED"
    mission.completed_at = datetime.now(timezone.utc)
    _event(db, mission, "ABORTED",
           f"Mission aborted by {actor or 'human'}."
           + (f" Reversed {reversed_count} actuation(s)." if reversed_count else ""))
    await db.commit()
    await db.refresh(mission)
    return _summary(mission, steps)


async def _reverse_mission_actions(db: AsyncSession, mission: Mission, steps) -> int:
    """Compensate any SoR actions produced by this mission's step executions."""
    try:
        from app.models.actuation import ActionRecord
        from app.services.actuation import Actuator
    except ImportError:
        # Actuation module not present in this build -> nothing to compensate.
        return 0
    exec_ids = [s.execution_id for s in steps if s.execution_id]
    if not exec_ids:
        return 0
    actions = (await db.execute(
        select(ActionRecord).where(
            ActionRecord.tenant_id == mission.tenant_id,
            ActionRecord.execution_id.in_(exec_ids),
            ActionRecord.status == "APPLIED",
        )
    )).scalars().all()
    count = 0
    for a in actions:
        try:
            await Actuator.reverse_action(db, tenant_id=mission.tenant_id,
                                          action_id=a.id, actor="mission-abort")
            count += 1
        except Exception as e:
            # One compensator failing must not abandon the remaining reversals,
            # but an un-reversed write to a system of record is an operator-
            # visible event, not a detail: log it loudly and leave the action
            # APPLIED so the drift monitor still reports it.
            logger.error(
                f"[mission] abort could not reverse action {a.id} "
                f"({a.system}:{a.external_id}); it remains APPLIED: {e}"
            )
    return count


def _summary(mission: Mission, steps) -> dict:
    return {
        "id": mission.id,
        "goal": mission.goal,
        "status": mission.status,
        "narrative": mission.narrative,
        "departments": mission.departments,
        "budget_usd": float(mission.budget_usd) if mission.budget_usd is not None else None,
        "spent_usd": round(float(mission.spent_usd or 0), 4),
        "created_at": mission.created_at.isoformat() if mission.created_at else None,
        "completed_at": mission.completed_at.isoformat() if mission.completed_at else None,
        "steps": [
            {
                "seq": s.seq, "name": s.name, "department": s.department,
                "skill_id": s.skill_id, "confidence": round(s.confidence or 0.0, 3),
                "depends_on": s.depends_on or [], "hitl_required": s.hitl_required,
                "status": s.status, "execution_id": s.execution_id,
                "result_summary": s.result_summary, "cost_usd": round(float(s.cost_usd or 0), 4),
            }
            for s in steps
        ],
    }
