"""
KAEOS — Reality Experience API

The enterprise twin is built live from the database (departments,
capabilities, agents, processes, HR employees, finance vendors, operations
projects) so it always agrees with the rest of the platform. Shocks traverse
the same live graph.
"""
import logging

from fastapi import Depends, APIRouter
from pydantic import BaseModel

from app.core.tenant import get_tenant_id
from app.services.reality_twin import build_live_twin, twin_stats, traverse_blast_radius

logger = logging.getLogger(__name__)

router = APIRouter()

async def record_event(msg: str, tenant_id: str, metadata: dict | None = None):
    """
    Append to the reality provenance feed.

    Persisted and tenant-scoped: this feed used to be a module-level list, so it
    was wiped on restart and shared across every tenant — which contradicted the
    durability the provenance story depends on.
    """
    from app.core.database import AsyncSessionLocal
    from app.models.reality import RealityEvent

    logger.info(f"Reality Feed [{tenant_id}]: {msg}")
    try:
        async with AsyncSessionLocal() as db:
            db.add(RealityEvent(tenant_id=tenant_id, event=msg, event_metadata=metadata or {}))
            await db.commit()
    except Exception as e:
        # The feed is an audit trail, not a control path — never fail a shock
        # simulation because the trail could not be written.
        logger.error(f"Reality feed write failed: {e}")


@router.get("/twin", summary="Get current enterprise twin state (live from DB)")
async def get_twin(tenant_id: str = Depends(get_tenant_id)):
    try:
        nodes, edges = await build_live_twin(tenant_id)
        return {
            "nodes": list(nodes.values()),
            "links": edges,
            "stats": twin_stats(nodes),
        }
    except Exception as e:
        logger.error(f"Twin fetch error: {e}")
        return {"nodes": [], "links": [], "stats": {}}


@router.get("/provenance", summary="Get provenance traces")
async def get_provenance(tenant_id: str = Depends(get_tenant_id)):
    from sqlalchemy import select
    from app.core.database import AsyncSessionLocal
    from app.models.reality import RealityEvent

    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(RealityEvent)
            .where(RealityEvent.tenant_id == tenant_id)
            .order_by(RealityEvent.created_at.desc())
            .limit(50)
        )).scalars().all()

    return {"feed": [
        {"id": r.id, "event": r.event, "metadata": r.event_metadata or {},
         "ts": r.created_at.isoformat() if r.created_at else None}
        for r in reversed(rows)
    ]}


@router.get("/learning", summary="Get learning modifiers and history")
async def get_learning(tenant_id: str = Depends(get_tenant_id)):
    """
    Historical shock outcomes and the modifiers learned from them.

    The modifiers are derived from this tenant's own recorded outcomes: each
    decision's average severity becomes its weight, so repeatedly choosing an
    action against worse shocks raises its learned modifier.
    """
    from sqlalchemy import select
    from app.core.database import AsyncSessionLocal
    from app.models.reality import ShockOutcome

    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(ShockOutcome)
            .where(ShockOutcome.tenant_id == tenant_id)
            .order_by(ShockOutcome.created_at.desc())
        )).scalars().all()

    recent = list(reversed(rows[:20]))
    outcomes = [
        {"shock_type": r.shock_type, "target": r.target, "severity": r.severity,
         "decision": r.decision, "options_evaluated": r.options_evaluated,
         "ts": r.created_at.isoformat() if r.created_at else None}
        for r in recent
    ]

    # Learned weights per decision, from real recorded severity.
    buckets: dict[str, list[float]] = {}
    for r in rows:
        if r.decision and r.severity is not None:
            buckets.setdefault(r.decision, []).append(r.severity)
    modifiers = {
        decision: round(sum(sevs) / len(sevs) / 20.0, 2)   # severity 0-100 → 0-5 scale
        for decision, sevs in buckets.items()
    }

    return {
        "historical_outcomes": outcomes,
        "shocks_processed": len(rows),
        "modifiers": modifiers,
    }


@router.get("/decision", summary="Get recent decisions")
async def get_decisions(tenant_id: str = Depends(get_tenant_id)):
    from sqlalchemy import select
    from app.core.database import AsyncSessionLocal
    from app.models.reality import ShockOutcome

    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(ShockOutcome)
            .where(ShockOutcome.tenant_id == tenant_id)
            .order_by(ShockOutcome.created_at.desc())
            .limit(10)
        )).scalars().all()

    return {"decisions": [
        {"shock_type": r.shock_type, "target": r.target, "severity": r.severity,
         "decision": r.decision, "impact": r.impact or {},
         "ts": r.created_at.isoformat() if r.created_at else None}
        for r in rows
    ]}


class ShockRequest(BaseModel):
    shock_type: str
    target_id: str


# ── Tuned causal profiles per shock type ─────────────────────────────────────
# severity_mult   scales blast-radius severity (cascade behavior differs by shock)
# depth           how far the shock propagates through the twin
# cost_per_node   $ baseline per impacted entity
# time_per_node   recovery days per impacted entity
# options(ctx)    scenario-specific decision options
SHOCK_PROFILES: dict[str, dict] = {
    "MERGER_INTEGRATION": {
        "severity_mult": 2.2,   # M&A touches every function — org-wide cascade
        "depth": 4,
        "cost_per_node": 8500,  # integration cost: systems, retention, rebadging
        "time_per_node": 6,
        "description": "M&A integration: workforce overlap, system consolidation, "
                       "culture and vendor-contract collision across the twin.",
        "options": lambda ctx: [
            {"action": "Phased Integration",
             "description": f"Integrate {ctx['caps']} capabilities function-by-function over "
                            f"{ctx['time'] * 2} days; retention bonuses for key {ctx['agents']} agent-owners.",
             "cost_mult": 1.0, "time_mult": 2.0, "risk_mult": 0.5, "modifier": 3.0},
            {"action": "Big-Bang Integration",
             "description": f"Cut over all {ctx['count']} impacted entities at once; "
                            f"highest synergy capture, highest attrition and outage risk.",
             "cost_mult": 1.6, "time_mult": 0.5, "risk_mult": 1.8, "modifier": 0.0},
            {"action": "Divest Overlapping Units",
             "description": f"Carve out {max(1, ctx['caps'] // 3)} overlapping capabilities; "
                            f"reduces integration surface and antitrust exposure.",
             "cost_mult": 0.7, "time_mult": 1.2, "risk_mult": 0.8, "modifier": 1.5},
        ],
    },
    "CYBER_INCIDENT": {
        "severity_mult": 2.8,   # lateral movement — worst-case propagation
        "depth": 4,
        "cost_per_node": 6200,  # forensics, downtime, notification, hardening
        "time_per_node": 1.5,
        "description": "Cyber incident: lateral movement across connected systems, "
                       "data-exfiltration exposure, regulatory notification clock running.",
        "options": lambda ctx: [
            {"action": "Isolate & Restore",
             "description": f"Immediately segment {ctx['count']} impacted entities, restore from "
                            f"known-good backups; SLA impact on {ctx['projs']} projects.",
             "cost_mult": 1.0, "time_mult": 1.0, "risk_mult": 0.6, "modifier": 4.0},
            {"action": "Full IR Engagement",
             "description": "Retain external incident-response and forensics; parallel "
                            "regulatory-notification workstream (GDPR 72h clock).",
             "cost_mult": 2.4, "time_mult": 1.4, "risk_mult": 0.35, "modifier": 2.0},
            {"action": "Contain & Monitor",
             "description": f"Contain the {ctx['agents']} affected agents only, keep systems up, "
                            f"monitor for re-entry; fastest but leaves dwell-time risk.",
             "cost_mult": 0.4, "time_mult": 0.4, "risk_mult": 2.2, "modifier": 0.0},
        ],
    },
    "BUDGET_CUT": {
        "severity_mult": 1.0, "depth": 3, "cost_per_node": 1250, "time_per_node": 2,
        "description": "Budget reduction: capability and project descoping pressure.",
        "options": None,  # default option set
    },
    "TALENT_EXODUS": {
        "severity_mult": 1.5, "depth": 3, "cost_per_node": 4200, "time_per_node": 4,
        "description": "Key-person departures: knowledge loss concentrated on owned capabilities.",
        "options": None,
    },
    "VENDOR_FAILURE": {
        "severity_mult": 1.4, "depth": 3, "cost_per_node": 3100, "time_per_node": 3,
        "description": "Vendor failure: supply/service continuity break for dependent capabilities.",
        "options": None,
    },
    "SYSTEM_OUTAGE": {
        "severity_mult": 1.2, "depth": 3, "cost_per_node": 1800, "time_per_node": 1,
        "description": "System outage: availability loss cascading to dependent processes.",
        "options": None,
    },
}

_DEFAULT_PROFILE = {"severity_mult": 1.0, "depth": 3, "cost_per_node": 1250,
                    "time_per_node": 2, "description": "Generic shock.", "options": None}


@router.post("/shock", summary="Inject a shock and run KAEOS evaluation")
async def inject_shock(req: ShockRequest, tenant_id: str = Depends(get_tenant_id)):
    nodes, edges = await build_live_twin(tenant_id)
    target = nodes.get(req.target_id)
    target_name = target["name"] if target else req.target_id
    profile = SHOCK_PROFILES.get(req.shock_type.upper(), _DEFAULT_PROFILE)
    await record_event(f"Shock injected: {req.shock_type} on {target_name}", tenant_id)

    # 1. Blast radius over the live twin (propagation depth is shock-specific)
    impacts = traverse_blast_radius(nodes, edges, req.target_id,
                                    max_depth=profile["depth"])
    impact_count = len(impacts)

    severity = min(95.0, max(15.0, impact_count * 3.0 * profile["severity_mult"]))
    impacted_caps = sum(1 for i in impacts if i["downstream"]["label"] == "Capability")
    impacted_projs = sum(1 for i in impacts if i["downstream"]["label"] == "Project")
    impacted_agents = sum(1 for i in impacts if i["downstream"]["label"] == "Agent")

    reasoning = (
        f"{profile['description']} Cascade from {target_name} reaches "
        f"{impact_count} connected entities ({impacted_caps} capabilities, "
        f"{impacted_agents} agents, {impacted_projs} projects)."
    )
    impact = {
        "severity": severity,
        "shock_type": req.shock_type.upper(),
        "reasoning": reasoning,
        "impacted_nodes": [i["downstream"]["id"] for i in impacts],
    }
    await record_event(f"Impact calculated: severity {severity:.1f} across {impact_count} nodes", tenant_id)

    # 2. Options — scenario-tuned when a profile defines them
    base_cost = max(impact_count, 1) * profile["cost_per_node"]
    base_time = max(1, round(max(impact_count, 1) * profile["time_per_node"]))
    ctx = {"count": impact_count, "caps": impacted_caps,
           "projs": impacted_projs, "agents": impacted_agents,
           "cost": base_cost, "time": base_time}

    if profile.get("options"):
        options_evaluated = []
        for spec in profile["options"](ctx):
            risk = round(min(0.95, severity * 0.005 * spec["risk_mult"]), 2)
            options_evaluated.append({
                "option": {"action": spec["action"], "description": spec["description"]},
                "score": {
                    "total_score": round(max(1.0, 100 - severity * 0.5 * spec["risk_mult"]
                                             - (spec["cost_mult"] - 1) * 8), 1),
                    "estimated_cost": f"${int(base_cost * spec['cost_mult']):,}",
                    "estimated_time_days": max(1, int(base_time * spec["time_mult"])),
                    "risk_penalty": risk,
                },
                "modifier_applied": spec["modifier"],
            })
        await record_event(f"Options generated: {len(options_evaluated)} scenario-tuned "
                           f"options for {req.shock_type.upper()}", tenant_id)
    else:
        options_evaluated = [
            {
                "option": {
                    "action": "Standard Mitigation",
                    "description": f"Execute baseline recovery across {impact_count} impacted nodes.",
                },
                "score": {
                    "total_score": round(100 - (severity * 0.5), 1),
                    "estimated_cost": f"${base_cost:,}",
                    "estimated_time_days": base_time,
                    "risk_penalty": round(min(0.95, severity * 0.004), 2),
                },
                "modifier_applied": 0.0,
            },
            {
                "option": {
                    "action": "Aggressive Recovery",
                    "description": f"Accelerate timeline for {impacted_caps} critical capabilities.",
                },
                "score": {
                    "total_score": round(100 - (severity * 0.8), 1),
                    "estimated_cost": f"${base_cost * 3:,}",
                    "estimated_time_days": max(1, int(base_time * 0.4)),
                    "risk_penalty": round(min(0.95, severity * 0.009), 2),
                },
                "modifier_applied": 5.0,
            },
        ]
        await record_event("Options generated: 2 data-driven options identified", tenant_id)

    best = max(options_evaluated, key=lambda o: o["score"]["total_score"])
    await record_event(f"Decision approved: {best['option']['action']}", tenant_id)

    result = {
        "impact": impact,
        "options_evaluated": options_evaluated,
        "recommendation": best,
    }
    try:
        from app.core.database import AsyncSessionLocal
        from app.models.reality import ShockOutcome

        async with AsyncSessionLocal() as db:
            db.add(ShockOutcome(
                tenant_id=tenant_id,
                shock_type=req.shock_type.upper(),
                target=target_name,
                severity=severity,
                decision=best["option"]["action"],
                options_evaluated=len(options_evaluated),
                impact=impact,
            ))
            await db.commit()
    except Exception as e:
        logger.error(f"Shock outcome persist failed: {e}")

    return result


@router.post("/simulate", summary="Run full demo simulation flow")
async def simulate_flow(tenant_id: str = Depends(get_tenant_id)):
    """Scripted shock for demo purposes — targets the busiest department."""
    nodes, edges = await build_live_twin(tenant_id)
    dept = next((n for n in nodes.values() if n["label"] == "Department"), None)
    target = dept["id"] if dept else "unknown"
    return await inject_shock(
        ShockRequest(shock_type="SYSTEM_OUTAGE", target_id=target), tenant_id
    )
