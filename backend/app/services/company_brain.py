"""The Company Brain — a self-improving, human-governed mission proposer.

KAEOS already records the operational reality of a tenant: the safe-autonomy
rate trend, cost, systems-of-record drift, mission outcomes, the knowledge
backlog. Everything reacts to those signals piecemeal; nothing SYNTHESISES them
into "here is what we should do about it." That synthesis is the brain.

``reflect_and_propose`` runs on a cadence. It:
  1. reconciles the outcome of past proposals (meta-learning input),
  2. OBSERVES the tenant's reality from real rows (never invented),
  3. scores each observation's materiality, weighted by how the human has
     historically treated proposals of that KIND (learn from acceptance +
     from the spawned mission's success),
  4. de-dups against what is already open or was recently rejected, and
  5. writes the survivors as PENDING proposals — inert until approved.

The governance boundary is the whole point: a proposal carries no authority.
``approve_proposal`` is the only path to action, and it routes through the
existing governed ``plan_mission`` so every spawned step still passes the 7
gates. The brain proposes; a human disposes; the gates execute.
"""
from __future__ import annotations

import logging
import os
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import select, func, or_, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.brain import BrainProposal
from app.models.missions import Mission

logger = logging.getLogger(__name__)

# Tuning knobs (deliberately conservative; the brain should feel considered,
# not chatty). ponytail: flat constants, lift to per-tenant settings if a big
# install wants a different appetite.
_MAX_NEW_PER_CYCLE = 3        # cap proposals raised in one reflection
_MAX_OPEN = 8                 # never flood the human past this many PENDING
_COOLDOWN_DAYS = 7            # suppress a rejected dedup_key for this long
_MIN_DECIDED_FOR_WEIGHT = 3   # below this, use a neutral learning prior
_METRIC_WINDOW_H = 48         # compare last 24h vs the prior 24h


# ── meta-learning: how has the human treated this KIND of proposal? ──────────
def weight_from_counts(approved: int, rejected: int, succeeded: int, failed: int) -> float:
    """The [0.5, 1.5] materiality multiplier, as a pure function of history.

    Up-weights kinds the human approves AND whose missions succeed; down-weights
    kinds that get rejected or that get approved but then fail. Neutral (1.0)
    until there is enough signal to be fair. Shared by the reflection cycle and
    the /brain/learning surface so the two can never drift apart."""
    decided = approved + rejected
    if decided < _MIN_DECIDED_FOR_WEIGHT:
        return 1.0
    accept_signal = approved / decided - 0.5
    success_signal = 0.0
    outcomes = succeeded + failed
    if outcomes:
        success_signal = succeeded / outcomes - 0.5
    return max(0.5, min(1.5, 1.0 + 0.5 * accept_signal + 0.5 * success_signal))


async def _signal_kind_weight(db: AsyncSession, tenant_id: str, kind: str) -> float:
    approved, rejected, succeeded, failed = (await db.execute(
        select(
            func.count().filter(BrainProposal.status == "APPROVED"),
            func.count().filter(BrainProposal.status == "REJECTED"),
            func.count().filter(and_(BrainProposal.status == "APPROVED",
                                     BrainProposal.outcome == "SUCCEEDED")),
            func.count().filter(and_(BrainProposal.status == "APPROVED",
                                     BrainProposal.outcome == "FAILED")),
        ).where(BrainProposal.tenant_id == tenant_id,
                BrainProposal.signal_kind == kind)
    )).one()
    return weight_from_counts(approved or 0, rejected or 0, succeeded or 0, failed or 0)


# ── outcome reconciliation: stamp a proposal from its mission's terminal state ─
_TERMINAL = {"COMPLETED": "SUCCEEDED", "FAILED": "FAILED", "ABORTED": "FAILED"}


async def _reconcile_outcomes(db: AsyncSession, tenant_id: str) -> int:
    """Close the meta-loop: an APPROVED proposal whose mission has reached a
    terminal state gets its outcome stamped, feeding _signal_kind_weight."""
    pending = (await db.execute(
        select(BrainProposal).where(
            BrainProposal.tenant_id == tenant_id, BrainProposal.status == "APPROVED",
            BrainProposal.outcome.is_(None), BrainProposal.mission_id.isnot(None))
    )).scalars().all()
    if not pending:
        return 0
    status_by_id = dict((await db.execute(
        select(Mission.id, Mission.status).where(
            Mission.tenant_id == tenant_id,
            Mission.id.in_([p.mission_id for p in pending])))).all())
    stamped = 0
    for p in pending:
        status = status_by_id.get(p.mission_id)
        if status in _TERMINAL:
            p.outcome = _TERMINAL[status]
            stamped += 1
    if stamped:
        await db.commit()
    return stamped


# ── observations: each returns a candidate dict grounded in real rows ────────
def _num(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


async def _metric_series(db: AsyncSession, tenant_id: str, key: str):
    """(recent_avg, prior_avg) over the two adjacent windows, or None if the
    series is too sparse to trend honestly (a fresh tenant has no history)."""
    from app.models.metrics_ts import MetricSample
    now = datetime.now(timezone.utc)
    since = now - timedelta(hours=_METRIC_WINDOW_H)
    mid = now - timedelta(hours=_METRIC_WINDOW_H // 2)
    rows = (await db.execute(
        select(MetricSample.bucket_start, MetricSample.value).where(
            MetricSample.tenant_id == tenant_id, MetricSample.metric_key == key,
            MetricSample.bucket_start >= since)
    )).all()
    recent = [_num(v) for b, v in rows if _as_utc(b) >= mid]
    prior = [_num(v) for b, v in rows if _as_utc(b) < mid]
    if len(recent) < 3 or len(prior) < 3:
        return None
    return sum(recent) / len(recent), sum(prior) / len(prior)


def _as_utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


async def _obs_autonomy_decline(db, tid):
    s = await _metric_series(db, tid, "safe_autonomy_rate")
    if not s:
        return None
    recent, prior = s
    drop = prior - recent
    if drop < 0.10 or recent >= 0.9:   # a dip while still-excellent isn't material
        return None
    return {
        "signal_kind": "AUTONOMY_DECLINE", "subject": "safe_autonomy_rate",
        "title": "Safe-autonomy rate is regressing",
        "goal": ("Diagnose why the safe-autonomy rate declined and tighten the "
                 "governance policy for the skills driving the regression."),
        "rationale": (f"The safe-autonomy rate fell from {prior:.0%} to {recent:.0%} "
                      f"over the last day — decisions are increasingly needing a human, "
                      f"which erodes the leverage the platform exists to create."),
        "evidence": [{"kind": "metric", "ref": "safe_autonomy_rate",
                      "detail": f"prior_24h={prior:.3f} recent_24h={recent:.3f} drop={drop:.3f}"}],
        "base_priority": min(1.0, drop * 3),
    }


async def _obs_cost_spike(db, tid):
    s = await _metric_series(db, tid, "cost_usd")
    if not s:
        return None
    recent, prior = s
    if prior <= 0:
        return None
    ratio = (recent - prior) / prior
    if ratio < 0.5:   # <50% up is noise
        return None
    return {
        "signal_kind": "COST_SPIKE", "subject": "cost_usd",
        "title": "Governed-execution cost is spiking",
        "goal": ("Investigate the rise in governed-execution cost and propose a "
                 "finance budget containment plan for the heaviest skills."),
        "rationale": (f"Average per-hour execution cost rose {ratio:.0%} over the last "
                      f"day (${prior:.2f} to ${recent:.2f} per bucket). Left unchecked "
                      f"this compounds into a real budget overrun."),
        "evidence": [{"kind": "metric", "ref": "cost_usd",
                      "detail": f"prior_avg={prior:.4f} recent_avg={recent:.4f} ratio={ratio:.3f}"}],
        "base_priority": min(1.0, ratio / 2),
    }


async def _obs_open_drift(db, tid):
    from app.models.event_mesh import ExternalSignal
    sig = (await db.execute(
        select(ExternalSignal).where(
            ExternalSignal.tenant_id == tid, ExternalSignal.kind == "DRIFT",
            ExternalSignal.status != "RESOLVED")
        .order_by(ExternalSignal.created_at.desc()).limit(1))).scalar_one_or_none()
    if sig is None:
        return None
    count = len(sig.matched_entities or []) or 1
    return {
        "signal_kind": "SOR_DRIFT", "subject": "drift",
        "title": f"{count} record(s) drifted outside KAEOS",
        "goal": ("Reconcile the systems-of-record records that changed outside KAEOS "
                 "and review the operations sync that let them diverge."),
        "rationale": (f"{sig.title}. The twin no longer matches the source of truth for "
                      f"these records; every governed decision made against a stale twin "
                      f"is a decision made on the wrong facts."),
        "evidence": [{"kind": "drift_signal", "ref": sig.id,
                      "detail": (sig.title or "")[:200]}],
        "base_priority": min(1.0, 0.4 + count * 0.05),
    }


async def _obs_mission_failures(db, tid):
    since = datetime.now(timezone.utc) - timedelta(days=7)
    fails = (await db.execute(
        select(Mission.departments).where(
            Mission.tenant_id == tid, Mission.status == "FAILED",
            Mission.created_at >= since))).scalars().all()
    if len(fails) < 3:
        return None
    depts = Counter(d[0] for d in fails if isinstance(d, list) and d)
    top_dept = depts.most_common(1)[0][0] if depts else None
    dept_clause = f" in {top_dept}" if top_dept else ""
    goal = (f"Diagnose the recurring{dept_clause} mission failures of the last week "
            f"and add a guardrail so the goal completes instead of failing.")
    return {
        "signal_kind": "MISSION_FAILURES", "subject": f"mission_failures:{top_dept or 'all'}",
        "title": f"{len(fails)} missions failed this week",
        "goal": goal,
        "rationale": (f"{len(fails)} missions reached FAILED in the last 7 days"
                      + (f", concentrated in {top_dept}" if top_dept else "")
                      + ". A repeated failure is a systemic gap, not bad luck — worth a "
                      "mission to find the root cause."),
        "evidence": [{"kind": "mission_failures", "ref": "missions",
                      "detail": f"count={len(fails)} by_dept={dict(depts)}"}],
        "base_priority": min(1.0, 0.3 + len(fails) * 0.1),
    }


async def _obs_elicitation_backlog(db, tid):
    try:
        from app.models.domain import ElicitationQuestion
    except Exception:
        return None
    cutoff = datetime.now(timezone.utc) - timedelta(days=3)
    count = (await db.execute(
        select(func.count()).select_from(ElicitationQuestion).where(
            ElicitationQuestion.tenant_id == tid,
            ElicitationQuestion.status == "PENDING",
            ElicitationQuestion.priority.in_(("HIGH", "CRITICAL")),
            ElicitationQuestion.created_at < cutoff))).scalar() or 0
    if count < 3:
        return None
    return {
        "signal_kind": "KNOWLEDGE_BACKLOG", "subject": "elicitation_backlog",
        "title": f"{count} expert questions unanswered",
        "goal": ("Clear the backlog of unanswered expert questions so the skills waiting "
                 "on that tacit knowledge can learn and raise their confidence."),
        "rationale": (f"{count} high-priority elicitation questions have gone unanswered "
                      f"for over 3 days. Each is a skill that cannot improve until the "
                      f"expert's unwritten rule is captured."),
        "evidence": [{"kind": "elicitation", "ref": "elicitation_questions",
                      "detail": f"pending_high_priority_over_3d={count}"}],
        "base_priority": min(1.0, 0.3 + count * 0.08),
    }


async def _obs_connector_health(db, tid):
    """CONNECTED systems that have stopped syncing: every hour they stay stale,
    the twin diverges further from the source of truth."""
    from app.models.domain import Connector
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    rows = (await db.execute(
        select(Connector.name, Connector.last_sync_at, Connector.connected_at)
        .where(Connector.tenant_id == tid, Connector.status == "CONNECTED"))).all()
    stale = []
    for name, last_sync, connected in rows:
        anchor = last_sync or connected
        if anchor is not None and _as_utc(anchor) < cutoff:
            stale.append(name)
    if not stale:
        return None
    names = ", ".join(stale[:3]) + (" and others" if len(stale) > 3 else "")
    return {
        "signal_kind": "CONNECTOR_STALE", "subject": "connector_health",
        "title": f"{len(stale)} connected system(s) stopped syncing",
        "goal": ("Diagnose why the connected external systems stopped syncing and "
                 "restore the data flow so the twin stays current."),
        "rationale": (f"{names} are connected but have not delivered records for "
                      f"over a day. Decisions grounded on a twin that has stopped "
                      f"receiving reality drift further from the truth every hour."),
        "evidence": [{"kind": "connector", "ref": "connectors",
                      "detail": f"stale_over_24h={len(stale)} names={stale[:5]}"}],
        "base_priority": min(1.0, 0.35 + len(stale) * 0.1),
    }


async def _obs_knowledge_decay(db, tid):
    """Executable rules past their half-life: governed decisions running on
    knowledge nobody has revalidated within its own declared shelf life."""
    from app.models.domain import Rule
    now = datetime.now(timezone.utc)
    rows = (await db.execute(
        select(Rule.validated_at, Rule.created_at, Rule.half_life_days)
        .where(Rule.tenant_id == tid, Rule.is_archived == False,  # noqa: E712
               Rule.is_executable == True)  # noqa: E712
        .limit(500))).all()
    expired = 0
    for validated_at, created_at, half_life in rows:
        anchor = validated_at or created_at
        if anchor is None or (now - _as_utc(anchor)).days > max(half_life or 0, 1):
            expired += 1
    if expired < 5:
        return None
    return {
        "signal_kind": "KNOWLEDGE_DECAY", "subject": "rule_half_life",
        "title": f"{expired} executable rules are past their half-life",
        "goal": ("Revalidate the expired executable rules with their domain experts "
                 "so governed decisions stop running on stale knowledge."),
        "rationale": (f"{expired} rules that agents actively execute have outlived "
                      f"their own declared half-life without revalidation. Each one "
                      f"is a decision policy the organization no longer knows to be true."),
        "evidence": [{"kind": "rule_decay", "ref": "rules",
                      "detail": f"expired_executable={expired} (of first {len(rows)} checked)"}],
        "base_priority": min(1.0, 0.3 + expired * 0.03),
    }


async def _obs_strategic_fitness(db, tid):
    """The EvolutionEngine's top structural recommendation, fed into the brain:
    fitness analysis was a proactive layer nothing consumed until now."""
    from app.services.evolution.evolution_engine import EvolutionEngine
    result = await EvolutionEngine().evaluate_and_evolve(tid)
    opts = result.get("optimizations") or []
    if not opts:
        return None
    top = opts[0]
    kind_slug = str(top.get("type") or "STRUCTURAL").lower()
    return {
        "signal_kind": "STRATEGIC_FITNESS", "subject": kind_slug,
        "title": "The fitness engine found a structural optimization",
        "goal": (f"Carry out the recommended structural change: {top.get('description', '')}"),
        "rationale": (f"Enterprise fitness analysis ranks this the highest-value "
                      f"structural move right now, worth about "
                      f"{float(top.get('expected_improvement') or 0):.1%} of fitness."),
        "evidence": [{"kind": "fitness", "ref": "evolution_engine",
                      "detail": (f"type={top.get('type')} current_fitness="
                                 f"{result.get('current_fitness')} "
                                 f"expected_improvement={top.get('expected_improvement')}")}],
        "base_priority": min(1.0, 0.3 + float(top.get("expected_improvement") or 0) * 2),
    }


_OBSERVERS = [_obs_autonomy_decline, _obs_cost_spike, _obs_open_drift,
              _obs_mission_failures, _obs_elicitation_backlog,
              _obs_connector_health, _obs_knowledge_decay, _obs_strategic_fitness]


async def _is_suppressed(db: AsyncSession, tenant_id: str, dedup_key: str) -> bool:
    """True if this condition already has an open proposal, or a human rejected
    the same condition inside the cooldown (the brain's memory of a 'no')."""
    cooldown = datetime.now(timezone.utc) - timedelta(days=_COOLDOWN_DAYS)
    row = (await db.execute(
        select(BrainProposal.id).where(
            BrainProposal.tenant_id == tenant_id, BrainProposal.dedup_key == dedup_key,
            or_(BrainProposal.status.in_(("PENDING", "APPROVED")),
                and_(BrainProposal.status == "REJECTED",
                     BrainProposal.decided_at >= cooldown)))
        .limit(1))).scalar_one_or_none()
    return row is not None


async def _polish_rationale(tenant_id: str, cand: dict) -> Optional[str]:
    """Best-effort LLM rewrite of the rationale into crisper executive prose.
    Never fatal, never changes the GOAL (that drives grounded planning) — only
    rewords the human-facing why. Skipped under the unit-test flag."""
    if os.environ.get("KAEOS_FAKE_LLM"):
        return None
    try:
        import asyncio
        from app.services.llm_router import LLMRouter
        router = await LLMRouter.for_tenant(tenant_id)
        res = await asyncio.wait_for(router.complete(
            prompt=(f"An autonomous operations brain proposes this action: {cand['goal']}\n"
                    f"Because: {cand['rationale']}\n"
                    "Rewrite the reason in ONE crisp sentence for a busy executive. "
                    "Plain text, no preamble."),
            model_tier="fast", max_tokens=90), timeout=30)
        text = res if isinstance(res, str) else res.get("content")
        if text and "fake_llm" not in text and "simulated" not in text.lower():
            return text.strip()[:600]
    except Exception as e:   # pragma: no cover - polish is decorative
        logger.debug("[brain] rationale polish skipped: %s", e)
    return None


async def reflect_and_propose(db: AsyncSession, tenant_id: str, *, use_llm: bool = True) -> dict:
    """One reflection cycle for a tenant. Returns a receipt of what it did."""
    await _reconcile_outcomes(db, tenant_id)

    open_count = (await db.execute(
        select(func.count()).select_from(BrainProposal).where(
            BrainProposal.tenant_id == tenant_id, BrainProposal.status == "PENDING"))).scalar() or 0
    room = max(0, min(_MAX_NEW_PER_CYCLE, _MAX_OPEN - open_count))
    if room == 0:
        return {"tenant_id": tenant_id, "observed": 0, "proposed": 0,
                "reason": "open-proposal cap reached"}

    # 1. Observe (each observer is isolated: one raising must not blind the brain
    # to the others).
    cands = []
    for obs in _OBSERVERS:
        try:
            c = await obs(db, tenant_id)
            if c:
                cands.append(c)
        except Exception as e:
            logger.warning("[brain] observer %s failed: %s", getattr(obs, "__name__", obs), e)

    # 2. Weight by learned materiality, drop suppressed, rank.
    scored = []
    for c in cands:
        c["dedup_key"] = f"{c['signal_kind']}:{c['subject']}"[:160]
        if await _is_suppressed(db, tenant_id, c["dedup_key"]):
            continue
        weight = await _signal_kind_weight(db, tenant_id, c["signal_kind"])
        c["priority"] = round(max(0.0, min(1.0, c["base_priority"] * weight)), 4)
        scored.append(c)
    scored.sort(key=lambda x: x["priority"], reverse=True)
    chosen = scored[:room]

    # 3. Persist as PENDING (inert). Optional LLM polish of the human-facing why.
    created = []
    for c in chosen:
        rationale = c["rationale"]
        if use_llm:
            polished = await _polish_rationale(tenant_id, c)
            if polished:
                rationale = polished
        p = BrainProposal(
            tenant_id=tenant_id, title=c["title"][:200], goal=c["goal"],
            rationale=rationale, evidence=c["evidence"], signal_kind=c["signal_kind"],
            dedup_key=c["dedup_key"], priority=c["priority"], status="PENDING")
        db.add(p)
        created.append(p)
    if created:
        await db.commit()
        # No per-row refresh: expire_on_commit=False, and every attribute read
        # below (id via default=_uuid, title, signal_kind, priority) is set
        # client-side, so a refresh SELECT per proposal buys nothing.
        for p in created:
            await _emit(tenant_id, "BRAIN_PROPOSAL_CREATED",
                        {"proposal_id": p.id, "title": p.title, "signal_kind": p.signal_kind,
                         "priority": p.priority})
    return {"tenant_id": tenant_id, "observed": len(cands), "proposed": len(created),
            "proposals": [{"id": p.id, "title": p.title, "priority": p.priority} for p in created]}


async def approve_proposal(db: AsyncSession, tenant_id: str, proposal_id: str,
                           approver: str) -> dict:
    """The ONLY path from a proposal to action. Plans a governed mission from the
    proposal's goal (every step still passes the 7 gates) and links it back."""
    p = (await db.execute(
        select(BrainProposal).where(
            BrainProposal.id == proposal_id, BrainProposal.tenant_id == tenant_id))
    ).scalar_one_or_none()
    if p is None:
        raise ValueError("proposal not found")
    if p.status != "PENDING":
        raise ValueError(f"proposal is {p.status}, not PENDING")

    from app.services.missions.planner import plan_mission
    mission = await plan_mission(db, tenant_id=tenant_id, goal=p.goal,
                                 created_by=f"brain:approved_by:{approver}")
    p.status = "APPROVED"
    p.mission_id = mission.id
    p.decided_at = datetime.now(timezone.utc)
    p.decided_by = approver
    await db.commit()
    await _emit(tenant_id, "BRAIN_MISSION_SPAWNED",
                {"proposal_id": p.id, "mission_id": mission.id, "approver": approver})
    return {"proposal_id": p.id, "status": "APPROVED", "mission_id": mission.id,
            "mission_status": mission.status}


async def reject_proposal(db: AsyncSession, tenant_id: str, proposal_id: str,
                          approver: str, reason: Optional[str] = None) -> dict:
    """Decline a proposal. The dedup_key is now suppressed for the cooldown, so
    the brain does not nag with the same idea — it learns the 'no'."""
    p = (await db.execute(
        select(BrainProposal).where(
            BrainProposal.id == proposal_id, BrainProposal.tenant_id == tenant_id))
    ).scalar_one_or_none()
    if p is None:
        raise ValueError("proposal not found")
    if p.status != "PENDING":
        raise ValueError(f"proposal is {p.status}, not PENDING")
    p.status = "REJECTED"
    p.decided_at = datetime.now(timezone.utc)
    p.decided_by = approver
    if reason:
        p.rationale = f"{p.rationale}\n\n[Rejected: {reason[:300]}]"
    await db.commit()
    return {"proposal_id": p.id, "status": "REJECTED"}


async def _emit(tenant_id: str, event_name: str, payload: dict) -> None:
    try:
        from app.services.event_bus import event_bus, EventType
        await event_bus.emit(getattr(EventType, event_name), payload, tenant_id)
    except Exception as e:   # non-fatal: a proposal must persist even if emit fails
        logger.debug("[brain] emit %s skipped: %s", event_name, e)


if __name__ == "__main__":
    # Self-check the meta-learning weight math without a DB: acceptance and
    # success both move the multiplier the right way and it stays bounded.
    assert weight_from_counts(4, 0, 4, 0) == 1.5, "all approved + all succeeded → max"
    assert weight_from_counts(0, 4, 0, 0) == 0.75, "all rejected, no outcomes yet → damped"
    assert weight_from_counts(2, 2, 0, 0) == 1.0, "neutral acceptance, no outcomes → neutral"
    assert weight_from_counts(4, 0, 0, 4) == 1.0, "approved but always fails → cancels out"
    assert weight_from_counts(1, 1, 0, 0) == 1.0, "below the decided floor → neutral prior"
    assert weight_from_counts(1, 9, 0, 1) == 0.55, "low acceptance + failure → strongly damped"
    print("company_brain weight self-check ok")
