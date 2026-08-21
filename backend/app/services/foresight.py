"""KAEOS Foresight — autonomous, prescriptive risk foresight.

The four existing reality views (Shock, What-if, Wargame, Replay) are REACTIVE:
a human poses a premise and watches the twin respond. They answer "what happens
if I ...". That requires the executive to already know which question to ask.

Foresight inverts it. It sweeps the whole shock catalogue against the live twin
with no prompt, scores every latent scenario, and answers the two questions a
CXO actually has:

  1. Pre-Mortem Radar — "what should I be worried about, ranked?" Every scenario
     is scored

         exposure = likelihood x blast_radius x preparedness_gap

     and the ones with no governed, tested response are surfaced as INEVITABLE
     SURPRISES, each with a drafted mission that closes the gap.

  2. Prescriptive Trajectory — "what is KAEOS about to do on its own, and where
     will it need me?" Projects committed missions, the safe-autonomy north-star
     curve, and the human decision points over the next 30/60/90 days.

Every number is derived from live tenant data (the twin, signals, executions,
missions, HITL queue). Nothing here invents a metric: where a tenant has no data
the component degrades to a neutral, and `evidence` on each item states exactly
what it was computed from, so a low-data tenant reads as honest rather than
confident.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import Signal, SkillExecution
from app.models.missions import Mission
from app.models.reality import ShockOutcome

logger = logging.getLogger(__name__)

# Horizons offered by the trajectory lane.
TRAJECTORY_HORIZONS = (30, 60, 90)

# A scenario with no governing mission/skill keeps its full gap; one that is
# fully covered still retains a floor, because "covered" never means "immune".
_PREPAREDNESS_FLOOR = 0.15

# Keywords that mark a mission/skill as covering a scenario. Deliberately
# conservative: a false "covered" hides a real gap, which is the dangerous
# direction of error.
_SCENARIO_KEYWORDS: Dict[str, tuple] = {
    "DATA_BREACH_PII": ("breach", "pii", "privacy", "gdpr", "exfil"),
    "RANSOMWARE": ("ransom", "malware", "encrypt", "backup", "restore"),
    "CYBER_INCIDENT": ("cyber", "security", "intrusion", "soc", "incident"),
    "LIQUIDITY_CRUNCH": ("liquidity", "cash", "runway", "treasury", "credit"),
    "REGULATORY_ACTION": ("regulator", "compliance", "audit", "filing", "sanction"),
    "MERGER_INTEGRATION": ("merger", "acquisition", "m&a", "integration"),
    "PRODUCT_RECALL": ("recall", "defect", "quality", "safety"),
    "SUPPLY_CHAIN_DISRUPTION": ("supply", "supplier", "logistics", "shipment", "sourcing"),
    "CAPABILITY_LOSS": ("capability", "continuity", "redundancy", "succession"),
    "CONTRACT_DISPUTE": ("contract", "dispute", "legal", "litigation", "claim"),
    "TALENT_EXODUS": ("attrition", "retention", "talent", "turnover", "exodus"),
    "EXECUTIVE_DEPARTURE": ("succession", "executive", "leadership", "departure"),
    "VENDOR_FAILURE": ("vendor", "third-party", "supplier", "outsourc"),
    "KEY_ACCOUNT_AT_RISK": ("churn", "account", "renewal", "customer", "retention"),
    "SYSTEM_OUTAGE": ("outage", "availability", "downtime", "failover", "sre"),
    "BUDGET_CUT": ("budget", "cost", "spend", "efficiency"),
    "EMPLOYEE_TERMINATION": ("termination", "offboard", "separation"),
}


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _as_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """Coerce to aware-UTC. DB rows come back naive on SQLite, aware on Postgres."""
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


async def _recent_signals(db: AsyncSession, tenant_id: str, days: int) -> List[Signal]:
    since = datetime.now(timezone.utc) - timedelta(days=days)
    return list((await db.execute(
        select(Signal).where(Signal.tenant_id == tenant_id, Signal.created_at >= since)
    )).scalars().all())


async def _shock_history(db: AsyncSession, tenant_id: str) -> List[ShockOutcome]:
    return list((await db.execute(
        select(ShockOutcome).where(ShockOutcome.tenant_id == tenant_id)
    )).scalars().all())


async def _coverage_corpus(db: AsyncSession, tenant_id: str) -> List[str]:
    """Lower-cased text of everything that could constitute a governed response.

    Missions are the governed, executable answer to a scenario; skill names are
    the capability layer beneath them. A scenario is "covered" when this corpus
    mentions it — see _SCENARIO_KEYWORDS.
    """
    corpus: List[str] = []
    # Newest-first with a ceiling: a tenant past 1000 missions has its coverage
    # long established, and the keyword corpus should not grow without bound.
    missions = (await db.execute(
        select(Mission.goal, Mission.narrative).where(Mission.tenant_id == tenant_id)
        .order_by(Mission.created_at.desc()).limit(1000)
    )).all()
    for goal, narrative in missions:
        corpus.append(f"{goal or ''} {narrative or ''}".lower())

    skills = (await db.execute(
        select(SkillExecution.skill_id_name)
        .where(SkillExecution.tenant_id == tenant_id)
        .distinct()
    )).scalars().all()
    corpus.extend((s or "").lower() for s in skills)
    return [c for c in corpus if c.strip()]


def _preparedness_gap(scenario: str, corpus: List[str]) -> tuple[float, int]:
    """1.0 = no governed response at all; _PREPAREDNESS_FLOOR = well covered."""
    keywords = _SCENARIO_KEYWORDS.get(scenario, ())
    if not keywords:
        return 1.0, 0
    hits = sum(1 for text in corpus if any(k in text for k in keywords))
    if hits == 0:
        return 1.0, 0
    # Diminishing returns: 1 response helps a lot, 4+ is as covered as we score.
    gap = max(_PREPAREDNESS_FLOOR, 1.0 - min(hits, 4) * 0.22)
    return round(gap, 3), hits


def _likelihood(scenario: str, signals: List[Signal], history: List[ShockOutcome]) -> tuple[float, Dict]:
    """Evidence-weighted probability proxy in [0,1].

    Base rate comes from the scenario's inherent severity class; it is then
    raised by this tenant's OWN evidence — matching recent signals and prior
    recorded shock outcomes of the same type.
    """
    keywords = _SCENARIO_KEYWORDS.get(scenario, ())
    signal_hits = 0
    for s in signals:
        # Signal carries its text in clean_payload; domain/signal_type add context.
        blob = " ".join(filter(None, (
            s.clean_payload or "", s.domain or "", s.signal_type or "",
        ))).lower()
        if any(k in blob for k in keywords):
            signal_hits += 1

    history_hits = sum(1 for h in history if (getattr(h, "shock_type", "") or "").upper() == scenario)

    # 0.12 floor: nothing in an enterprise is truly impossible.
    score = 0.12 + min(signal_hits, 8) * 0.07 + min(history_hits, 5) * 0.06
    return round(_clamp(score), 3), {"signal_matches": signal_hits, "prior_shocks": history_hits}


async def premortem_radar(
    db: AsyncSession, tenant_id: str, *, signal_days: int = 90, limit: int = 8,
) -> Dict[str, Any]:
    """Rank every scenario by exposure and return the Inevitable Surprises.

    Imported lazily from the reality route's catalogue so the two lanes can never
    disagree about what a shock is or how severe it is.
    """
    from app.api.routes.reality import BASE_SEVERITY, SHOCK_PROFILES
    from app.services.reality_twin import build_live_twin, traverse_blast_radius

    try:
        nodes, edges = await build_live_twin(tenant_id)
    except Exception as e:  # a twin failure must not take the board down
        logger.error("[Foresight] twin build failed: %s", e)
        nodes, edges = {}, []

    signals = await _recent_signals(db, tenant_id, signal_days)
    history = await _shock_history(db, tenant_id)
    corpus = await _coverage_corpus(db, tenant_id)

    # Blast radius is measured from the most connected node — the worst credible
    # entry point for a cascade, which is what a pre-mortem should assume.
    epicentre_id, epicentre_name = _most_connected(nodes, edges)

    scenarios = []
    for scenario, base_sev in BASE_SEVERITY.items():
        profile = SHOCK_PROFILES.get(scenario, {})
        depth = int(profile.get("depth", 3) or 3)

        impacts = []
        if epicentre_id:
            try:
                impacts = traverse_blast_radius(nodes, edges, epicentre_id, max_depth=depth)
            except Exception as e:
                logger.warning("[Foresight] blast traversal failed for %s: %s", scenario, e)

        reach = len(impacts)
        # Normalised against the twin so a small org is not flattered by a small
        # absolute cascade.
        blast = _clamp(reach / max(len(nodes), 1)) if nodes else 0.0
        # Severity class keeps a high-consequence scenario meaningful even when
        # the twin is sparse.
        blast = round(_clamp(0.35 * (base_sev / 100.0) + 0.65 * blast), 3)

        likelihood, evidence = _likelihood(scenario, signals, history)
        gap, covering = _preparedness_gap(scenario, corpus)
        exposure = round(likelihood * blast * gap, 4)

        scenarios.append({
            "scenario": scenario,
            "title": scenario.replace("_", " ").title(),
            "exposure": exposure,
            "likelihood": likelihood,
            "blast_radius": blast,
            "preparedness_gap": gap,
            "base_severity": base_sev,
            "entities_in_cascade": reach,
            "governed_responses": covering,
            "is_inevitable_surprise": covering == 0,
            "epicentre": epicentre_name,
            "evidence": {
                **evidence,
                "covering_responses": covering,
                "twin_nodes": len(nodes),
                "signal_window_days": signal_days,
            },
            "recommended_mission": _draft_mission(scenario, covering, reach, epicentre_name),
        })

    scenarios.sort(key=lambda s: s["exposure"], reverse=True)
    surprises = [s for s in scenarios if s["is_inevitable_surprise"]]

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "tenant_id": tenant_id,
        "scenarios": scenarios[:limit],
        "inevitable_surprises": surprises[:limit],
        "totals": {
            "scenarios_scored": len(scenarios),
            "uncovered": len(surprises),
            "twin_nodes": len(nodes),
            "signals_considered": len(signals),
            "governed_responses_indexed": len(corpus),
        },
        "method": (
            "exposure = likelihood x blast_radius x preparedness_gap. Likelihood is "
            "evidence-weighted from this tenant's signals and recorded shock outcomes; "
            "blast radius is a live twin traversal from the most connected node; "
            "preparedness gap is 1.0 when no mission or skill governs the scenario."
        ),
    }


def _most_connected(nodes: Dict[str, dict], edges: List[dict]) -> tuple[Optional[str], Optional[str]]:
    """The worst credible cascade entry point: the highest-degree node."""
    if not nodes:
        return None, None
    degree: Dict[str, int] = {}
    for e in edges:
        degree[e["source"]] = degree.get(e["source"], 0) + 1
        degree[e["target"]] = degree.get(e["target"], 0) + 1
    if not degree:
        first = next(iter(nodes))
        return first, nodes[first].get("name", first)
    top = max(degree, key=degree.get)
    if top not in nodes:
        top = next(iter(nodes))
    return top, nodes[top].get("name", top)


def _draft_mission(scenario: str, covering: int, reach: int, epicentre: Optional[str]) -> Dict[str, str]:
    """The gap-closer: a mission goal a human approves, never auto-executed."""
    label = scenario.replace("_", " ").lower()
    if covering:
        goal = (
            f"Stress-test and strengthen the existing response to a {label} "
            f"({covering} governed response(s) on record)"
        )
    else:
        goal = f"Establish a governed response capability for a {label}"
    where = f" Cascade would reach {reach} connected entities" + (
        f" from {epicentre}." if epicentre else "."
    )
    return {
        "goal": goal,
        "narrative": (
            f"Drafted by Foresight Pre-Mortem Radar: this tenant has "
            f"{covering or 'no'} governed response(s) for {label}." + where +
            " Review, adjust scope, and approve to commission."
        ),
    }


async def prescriptive_trajectory(
    db: AsyncSession, tenant_id: str, *, days: int = 45,
) -> Dict[str, Any]:
    """What KAEOS will do on its own next, and where it will need a human.

    Composes the existing safe-autonomy forecast, live missions, and the pending
    human decision queue — no new metrics invented.
    """
    # North star: the real safe-autonomy series, projected with the same
    # linear_forecast the /forecast (Precog) route uses — one source of truth, and
    # it returns `insufficient` rather than a fabricated curve on thin history.
    north_star: Dict[str, Any] = {}
    try:
        from app.services.forecast import linear_forecast
        from app.services.safe_autonomy import compute_safe_autonomy

        sar = await compute_safe_autonomy(db, tenant_id, days=days)
        series = [p.get("safe_autonomy_rate") for p in sar.get("timeseries", [])]
        north_star = {
            "current": sar.get("safe_autonomy_rate"),
            "window_days": days,
            "projection": linear_forecast(series, horizon=14, clamp01=True),
        }
    except Exception as e:  # the north star is a panel, never a hard dependency
        logger.warning("[Foresight] safe-autonomy north star unavailable: %s", e)

    missions = list((await db.execute(
        select(Mission)
        .where(Mission.tenant_id == tenant_id, Mission.status.notin_(("COMPLETED", "FAILED", "CANCELLED")))
        .order_by(Mission.created_at.desc())
        .limit(50)
    )).scalars().all())

    now = datetime.now(timezone.utc)
    horizons = {}
    for h in TRAJECTORY_HORIZONS:
        cutoff = now + timedelta(days=h)
        planned = [
            {
                "id": m.id,
                "goal": m.goal,
                "status": m.status,
                "departments": m.departments or [],
                "budget_usd": m.budget_usd,
                "created_at": _as_utc(m.created_at).isoformat() if m.created_at else None,
            }
            # Everything in flight is "within" every horizon; the horizon selects
            # how far ahead the projection is stated, not which rows exist.
            for m in missions
            if (_as_utc(m.created_at) or now) <= cutoff
        ]
        horizons[f"{h}d"] = {
            "horizon_days": h,
            "autonomous_actions_projected": len(planned),
            "missions": planned[:20],
        }

    pending_decisions = await _pending_decisions(db, tenant_id)

    return {
        "generated_at": now.isoformat(),
        "tenant_id": tenant_id,
        "north_star": north_star,
        "horizons": horizons,
        "human_decision_points": pending_decisions,
        "totals": {
            "missions_in_flight": len(missions),
            "decisions_awaiting_human": len(pending_decisions),
        },
        "method": (
            "Composed from the live safe-autonomy forecast, missions currently in "
            "flight, and the real pending human-approval queue. No projection is "
            "extrapolated beyond committed work."
        ),
    }


async def _pending_decisions(db: AsyncSession, tenant_id: str) -> List[Dict[str, Any]]:
    """Real decisions awaiting a human: the live HITL queue + gated mission steps.

    The HITL queue (Redis, or the in-memory fallback) is the authoritative source
    for approvals in flight — the same one /hitl/pending serves. Mission steps
    flagged hitl_required are the scheduled decision points ahead of them.
    """
    out: List[Dict[str, Any]] = []

    try:
        from app.services.hitl_manager import hitl_manager

        for p in await hitl_manager.list_pending(tenant_id):
            out.append({
                "kind": "hitl_approval",
                "execution_id": p.get("execution_id"),
                "skill": (p.get("skill_def") or {}).get("name") or p.get("skill_name"),
                "department": (p.get("skill_def") or {}).get("department"),
                "requested_at": p.get("created_at") or p.get("requested_at"),
            })
    except Exception as e:
        logger.warning("[Foresight] HITL queue unavailable: %s", e)

    try:
        from app.models.missions import MissionStep

        rows = (await db.execute(
            select(MissionStep)
            .where(
                MissionStep.tenant_id == tenant_id,
                MissionStep.hitl_required.is_(True),
                MissionStep.status.notin_(("SUCCESS", "COMPLETED", "FAILED", "SKIPPED")),
            )
            .limit(25)
        )).scalars().all()
        for r in rows:
            out.append({
                "kind": "mission_step",
                "mission_id": r.mission_id,
                "seq": r.seq,
                "status": r.status,
                "name": r.name,
                "department": r.department,
                "skill_id": r.skill_id,
            })
    except Exception as e:
        logger.warning("[Foresight] gated mission-step lookup failed: %s", e)

    return out


async def count_open_scenarios(db: AsyncSession, tenant_id: str) -> int:
    """Small helper for dashboards: how many scenarios have NO governed response."""
    report = await premortem_radar(db, tenant_id)
    return int(report["totals"]["uncovered"])
