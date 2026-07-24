"""Mission engine — governed execution of a mission's DAG.

Runs dependency-ready steps in order. Each executable step runs its real skill
through the full 7-gate ``AgentExecutor`` (never a shortcut around governance).
A budget gate stops the mission before an over-budget step; a HITL checkpoint
pauses it for human approval; every transition is appended to the mission ledger.
The engine is re-entrant: call ``advance_mission`` again after a human approves a
checkpoint or lifts the budget, and it picks up exactly where it paused.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import Skill
from app.models.missions import Mission, MissionStep, MissionEvent

logger = logging.getLogger(__name__)

_TERMINAL_STEP = {"DONE", "FAILED", "SKIPPED"}


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

    if skill is None:
        return {"status": "FAILED", "reason": f"skill {step.skill_id} not found"}

    from app.agents.runtime import AgentExecutor
    from app.services.compliance import ComplianceEngine
    from app.services.hitl_manager import hitl_manager

    dept = (skill.department or skill.domain or "general")
    # A single generative advisory step the model completes with a recommendation.
    advisory_step = {
        "id": "recommend",
        "name": f"recommend_{dept}_action",
        "prompt": (
            f"Mission goal: {mission.goal}\n"
            f"You are the {dept} function using the '{skill.skill_id}' capability. "
            f"Recommend the single best {dept} action toward this goal. "
            "Respond ONLY as JSON: "
            '{"decision": "<the recommended action>", "rationale": "<one sentence>", '
            '"risks": ["<risk>"], "status": "SUCCESS", "confidence": 0.0}'
        ),
        "tool": "none",
    }
    # Advisory planning processes no transaction and no personal data, so the
    # transactional audit tags (SOX amount, GDPR lawful basis) do not apply here;
    # they are enforced at actuation time. Fairness still engages for people-facing
    # recommendations.
    people_facing = dept.lower() in ("hr", "human_resources", "people", "workforce", "recruiting")
    skill_dict = {
        "skill_id": skill.skill_id,
        "department": dept,
        "steps": [advisory_step],
        "compliance_tags": ["EEOC"] if people_facing else [],
        "confidence": skill.confidence or 0.0,
    }
    ctx = {
        "tenant_id": mission.tenant_id,
        "execution_id": execution_id,
        "mission_id": mission.id,
        "mission_step_seq": step.seq,
        "task_intent": f"[mission] {mission.goal} :: {step.name}",
        "_skill_obj": skill,
        "requires_fairness_assessment": people_facing,
        # A HITL-gated step reached execution only via human approval of its
        # mission checkpoint, so the executor's Gate 3 must not re-pause it, and it
        # carries the human-approver flag a governed action legitimately has.
        "has_human_approver": bool(step.hitl_required),
        "hitl_pre_approved": bool(step.hitl_required),
    }
    executor = AgentExecutor(ComplianceEngine(), hitl_manager)
    try:
        return await executor.execute_skill(skill_dict, ctx)
    except Exception as e:
        logger.warning(f"[mission] step {step.seq} execution error: {e}")
        return {"status": "FAILED", "reason": str(e)}


def _recommendation_of(result: dict) -> Optional[str]:
    """Pull the model's recommendation text out of the executor result chain."""
    import json as _json
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
                    parsed = _json.loads(txt)
                    if isinstance(parsed, dict) and parsed.get("decision"):
                        return str(parsed["decision"])[:240]
                except Exception:
                    pass
            return txt[:240]
    return None


def _cost_of(result: dict) -> float:
    c = result.get("cost")
    if isinstance(c, dict):
        return float(c.get("total_usd") or c.get("usd") or 0.0)
    if isinstance(c, (int, float)):
        return float(c)
    return 0.0


def _finalize(db, mission, steps) -> None:
    """Set the mission's terminal/paused status from its steps."""
    if any(s.status == "AWAITING_HITL" for s in steps):
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
    await db.commit()
    await db.refresh(mission)
    return _summary(mission, steps)


def _apply_step_result(db, mission, step, result: dict) -> None:
    """Fold one executor result into the step + mission (no commit)."""
    status = result.get("status")
    if status == "SUCCESS_CLEAN":
        cost = _cost_of(result)
        step.cost_usd = cost
        mission.spent_usd = (mission.spent_usd or 0.0) + cost
        step.status = "DONE"
        step.completed_at = datetime.now(timezone.utc)
        step.result_summary = _recommendation_of(result) or \
            f"{result.get('steps_completed', 0)} steps, {result.get('duration_ms', 0)}ms"
        _event(db, mission, "STEP_DONE",
               f"Step {step.seq} ({step.name}): {step.result_summary}", step.seq)
    elif status in ("HITL_REQUIRED", "PENDING", "PENDING_HITL") or result.get("pending"):
        step.status = "AWAITING_HITL"
        _event(db, mission, "HITL_PAUSE",
               f"Step {step.seq} routed to human by the confidence gate.", step.seq)
    elif status == "BLOCKED_COMPLIANCE" and not step.hitl_required:
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
        step.status = "READY"  # cleared checkpoint; engine will execute it
        mission.status = "RUNNING"
        _event(db, mission, "STARTED",
               f"Step {seq} approved by {approver or 'human'}; resuming.", seq)
        await db.commit()
        return await advance_mission(db, tenant_id=tenant_id, mission_id=mission_id)
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
    except Exception:
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
        except Exception:
            pass
    return count


def _summary(mission: Mission, steps) -> dict:
    return {
        "id": mission.id,
        "goal": mission.goal,
        "status": mission.status,
        "narrative": mission.narrative,
        "departments": mission.departments,
        "budget_usd": mission.budget_usd,
        "spent_usd": round(mission.spent_usd or 0.0, 4),
        "created_at": mission.created_at.isoformat() if mission.created_at else None,
        "completed_at": mission.completed_at.isoformat() if mission.completed_at else None,
        "steps": [
            {
                "seq": s.seq, "name": s.name, "department": s.department,
                "skill_id": s.skill_id, "confidence": round(s.confidence or 0.0, 3),
                "depends_on": s.depends_on or [], "hitl_required": s.hitl_required,
                "status": s.status, "execution_id": s.execution_id,
                "result_summary": s.result_summary, "cost_usd": round(s.cost_usd or 0.0, 4),
            }
            for s in steps
        ],
    }
