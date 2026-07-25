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

from app.core.tenant import get_tenant_id, require_role
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
        # Stats reflect the FULL org (honest counts); the drawn constellation is a
        # legible per-department sample so it never degrades into a hairball.
        stats = twin_stats(nodes)
        from app.services.reality_twin import sample_twin_for_view
        view_nodes, view_edges = sample_twin_for_view(nodes, edges)
        return {
            "nodes": list(view_nodes.values()),
            "links": view_edges,
            "stats": stats,
            "sampled": len(view_nodes) < len(nodes),
            "total_nodes": len(nodes),
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
    "DATA_BREACH_PII": {
        "severity_mult": 2.6, "depth": 4, "cost_per_node": 5800, "time_per_node": 2,
        "description": "PII data breach: customer records exposed, the breach-notification "
                       "clock is running, class-action and regulatory exposure open.",
        "options": lambda ctx: [
            {"action": "Notify + Credit Monitoring",
             "description": f"Disclose within the statutory window and offer monitoring to affected "
                            f"customers across {ctx['count']} touchpoints; reputational hit, legal safe-harbor.",
             "cost_mult": 1.4, "time_mult": 1.0, "risk_mult": 0.5, "modifier": 4.0},
            {"action": "Privilege Review First",
             "description": "Scope exposure under legal privilege before disclosing; measured, "
                            "but risks blowing the notification clock.",
             "cost_mult": 1.1, "time_mult": 1.6, "risk_mult": 1.3, "modifier": 1.0},
            {"action": "Full Public Disclosure",
             "description": "Immediate transparent disclosure and remediation; maximum trust play, "
                            "maximum short-term damage.",
             "cost_mult": 1.7, "time_mult": 0.6, "risk_mult": 0.8, "modifier": 2.5},
        ],
    },
    "RANSOMWARE": {
        "severity_mult": 2.7, "depth": 4, "cost_per_node": 6400, "time_per_node": 2,
        "description": "Ransomware: systems encrypted, operations halted, an extortion "
                       "demand with a countdown - recovery vs. ransom trade-off.",
        "options": lambda ctx: [
            {"action": "Restore from Immutable Backup",
             "description": f"Rebuild {ctx['count']} impacted systems from air-gapped backups; "
                            f"no ransom paid, longer downtime.",
             "cost_mult": 1.2, "time_mult": 1.4, "risk_mult": 0.5, "modifier": 4.5},
            {"action": "Negotiate Decryption",
             "description": "Engage a negotiator for a decryptor; fastest theoretical recovery, "
                            "funds the adversary, no guarantee.",
             "cost_mult": 2.8, "time_mult": 0.6, "risk_mult": 2.3, "modifier": 0.0},
            {"action": "Clean-Room Rebuild",
             "description": f"Stand up a fresh environment for {ctx['caps']} capabilities and migrate "
                            f"verified data; safest, slowest.",
             "cost_mult": 1.9, "time_mult": 2.4, "risk_mult": 0.6, "modifier": 2.5},
        ],
    },
    "REGULATORY_ACTION": {
        "severity_mult": 2.0, "depth": 3, "cost_per_node": 5400, "time_per_node": 5,
        "description": "Regulatory enforcement: a finding lands with a remediation clock "
                       "and fine exposure across legal, finance and the cited function.",
        "options": lambda ctx: [
            {"action": "Remediate & Self-Report",
             "description": f"Fix the {ctx['caps']} cited capabilities and voluntarily disclose; "
                            f"cooperation credit lowers penalties.",
             "cost_mult": 1.0, "time_mult": 1.3, "risk_mult": 0.5, "modifier": 4.0},
            {"action": "Contest the Finding",
             "description": f"Challenge the ruling with outside counsel across {ctx['count']} entities; "
                            f"prolonged uncertainty.",
             "cost_mult": 1.8, "time_mult": 2.5, "risk_mult": 1.6, "modifier": 0.0},
            {"action": "Negotiated Settlement",
             "description": "Consent decree with agreed controls; fastest closure, on-record finding.",
             "cost_mult": 1.3, "time_mult": 0.7, "risk_mult": 0.8, "modifier": 2.0},
        ],
    },
    "CONTRACT_DISPUTE": {
        "severity_mult": 1.4, "depth": 3, "cost_per_node": 4100, "time_per_node": 4,
        "description": "Contract dispute: a counterparty breach threatens revenue recognition "
                       "and triggers legal exposure on the flagged agreement.",
        "options": lambda ctx: [
            {"action": "Enforce & Litigate",
             "description": "Assert rights and pursue damages; strongest position, longest and costliest path.",
             "cost_mult": 1.9, "time_mult": 2.6, "risk_mult": 1.4, "modifier": 1.0},
            {"action": "Renegotiate Terms",
             "description": f"Amend the agreement to preserve the relationship across {ctx['count']} "
                            f"touchpoints; pragmatic.",
             "cost_mult": 0.9, "time_mult": 1.0, "risk_mult": 0.6, "modifier": 4.0},
            {"action": "Settle & Release",
             "description": "Mutual release for a defined payment; certainty now, precedent risk.",
             "cost_mult": 1.3, "time_mult": 0.5, "risk_mult": 0.8, "modifier": 2.0},
        ],
    },
    "SUPPLY_CHAIN_DISRUPTION": {
        "severity_mult": 1.6, "depth": 3, "cost_per_node": 3600, "time_per_node": 3,
        "description": "Supply-chain disruption: a critical supplier fails, breaking "
                       "procurement continuity for dependent operations.",
        "options": lambda ctx: [
            {"action": "Activate Dual-Source",
             "description": f"Shift volume to the qualified backup supplier for {ctx['count']} lines; "
                            f"higher unit cost, continuity preserved.",
             "cost_mult": 1.3, "time_mult": 0.8, "risk_mult": 0.5, "modifier": 3.5},
            {"action": "Air-Freight Buffer",
             "description": "Expedite inventory to bridge the gap; premium logistics, fastest recovery.",
             "cost_mult": 2.2, "time_mult": 0.3, "risk_mult": 0.7, "modifier": 1.5},
            {"action": "Re-engineer the BoM",
             "description": f"Redesign to remove the single point of failure across {ctx['caps']} "
                            f"capabilities; slow but durable.",
             "cost_mult": 1.6, "time_mult": 3.0, "risk_mult": 1.1, "modifier": 2.0},
        ],
    },
    "PRODUCT_RECALL": {
        "severity_mult": 1.9, "depth": 3, "cost_per_node": 4700, "time_per_node": 3,
        "description": "Product recall: a quality defect surfaces, forcing a safety, cost "
                       "and reputation decision across ops, support and legal.",
        "options": lambda ctx: [
            {"action": "Voluntary Recall",
             "description": f"Proactively recall across {ctx['count']} impacted lines; highest cost, "
                            f"protects trust and pre-empts regulators.",
             "cost_mult": 2.0, "time_mult": 1.2, "risk_mult": 0.5, "modifier": 4.0},
            {"action": "Field Retrofit",
             "description": "Fix units in place via service; lower cost, slower coverage.",
             "cost_mult": 1.1, "time_mult": 1.8, "risk_mult": 1.0, "modifier": 2.0},
            {"action": "Monitor + Advisory",
             "description": "Issue a usage advisory and watch failure rates; cheapest, carries liability "
                            "if defects spread.",
             "cost_mult": 0.4, "time_mult": 0.6, "risk_mult": 2.0, "modifier": 0.0},
        ],
    },
    "KEY_ACCOUNT_AT_RISK": {
        "severity_mult": 1.5, "depth": 3, "cost_per_node": 2600, "time_per_node": 2,
        "description": "Strategic account at risk: the flagged account signals churn, threatening "
                       "revenue and reference value across sales, support and finance.",
        "options": lambda ctx: [
            {"action": "Executive Save Play",
             "description": "CRO-led save with a tailored success plan and roadmap commitments; "
                            "high-touch, high-retention.",
             "cost_mult": 1.2, "time_mult": 0.8, "risk_mult": 0.5, "modifier": 4.0},
            {"action": "Retention Discount",
             "description": "Multi-year renewal at a concession; protects the logo, compresses margin.",
             "cost_mult": 1.6, "time_mult": 0.4, "risk_mult": 0.7, "modifier": 1.5},
            {"action": "Managed Offboarding",
             "description": "Accept the churn, secure a reference and orderly wind-down; preserves goodwill.",
             "cost_mult": 0.5, "time_mult": 1.2, "risk_mult": 1.4, "modifier": 0.0},
        ],
    },
    "LIQUIDITY_CRUNCH": {
        "severity_mult": 2.1, "depth": 4, "cost_per_node": 2200, "time_per_node": 3,
        "description": "Liquidity crunch: cash runway compresses, forcing a financing, cost "
                       "or asset decision across the whole org.",
        "options": lambda ctx: [
            {"action": "Bridge Financing",
             "description": "Raise a bridge facility to extend runway; dilution/interest cost, operations intact.",
             "cost_mult": 1.5, "time_mult": 0.7, "risk_mult": 0.8, "modifier": 3.0},
            {"action": "Cost Freeze + RIF",
             "description": f"Freeze spend and reduce force across {ctx['caps']} capabilities; preserves "
                            f"cash, real capability loss.",
             "cost_mult": 0.4, "time_mult": 1.0, "risk_mult": 1.6, "modifier": 1.0},
            {"action": "Non-Core Asset Sale",
             "description": "Divest a non-core unit for immediate cash; one-time inflow, narrower footprint.",
             "cost_mult": 0.8, "time_mult": 1.4, "risk_mult": 1.0, "modifier": 2.5},
        ],
    },
    "SEV1_ESCALATION": {
        "severity_mult": 1.8, "depth": 3, "cost_per_node": 2400, "time_per_node": 0.8,
        "description": "SEV-1 incident: a production-critical failure escalates, hitting "
                       "availability, support load and customer trust.",
        "options": lambda ctx: [
            {"action": "All-Hands War Room",
             "description": f"Convene a cross-functional war room on the {ctx['count']} impacted "
                            f"entities; fastest resolution, high burn.",
             "cost_mult": 1.6, "time_mult": 0.3, "risk_mult": 0.5, "modifier": 4.0},
            {"action": "Rollback + Failover",
             "description": "Revert the change and fail over to standby; quick and safe if a clean version exists.",
             "cost_mult": 0.7, "time_mult": 0.5, "risk_mult": 0.9, "modifier": 2.5},
            {"action": "Degrade Gracefully",
             "description": "Shed non-critical features to stabilize core service; buys time, partial outage persists.",
             "cost_mult": 0.5, "time_mult": 0.8, "risk_mult": 1.3, "modifier": 1.0},
        ],
    },
    "EXECUTIVE_DEPARTURE": {
        "severity_mult": 1.5, "depth": 3, "cost_per_node": 5000, "time_per_node": 6,
        "description": "Executive departure: a key leader exits, creating decision, morale "
                       "and continuity risk across owned functions.",
        "options": lambda ctx: [
            {"action": "Internal Promotion",
             "description": f"Elevate a proven internal leader over the {ctx['agents']} affected teams; "
                            f"continuity, unproven at scale.",
             "cost_mult": 0.8, "time_mult": 0.6, "risk_mult": 0.8, "modifier": 3.5},
            {"action": "External Executive Search",
             "description": "Run a retained search for a seasoned hire; best-fit talent, long vacancy and ramp.",
             "cost_mult": 1.8, "time_mult": 2.4, "risk_mult": 1.0, "modifier": 1.5},
            {"action": "Interim + Retention",
             "description": "Appoint an interim and lock in the leadership bench; stabilizes, defers the decision.",
             "cost_mult": 1.1, "time_mult": 1.0, "risk_mult": 0.7, "modifier": 2.5},
        ],
    },
    "EMPLOYEE_TERMINATION": {
        "severity_mult": 0.9, "depth": 2, "cost_per_node": 2100, "time_per_node": 3,
        "description": "Key-employee termination: concentrated knowledge and access loss on "
                       "the owned capability, with re-hire and coverage gaps.",
        "options": lambda ctx: [
            {"action": "Backfill + Knowledge Transfer",
             "description": "Structured handover and a targeted backfill; continuity-first, moderate cost.",
             "cost_mult": 1.0, "time_mult": 1.2, "risk_mult": 0.5, "modifier": 3.5},
            {"action": "Redistribute Load",
             "description": f"Absorb the work across the remaining {ctx['agents']} owners; no hire, "
                            f"burnout risk.",
             "cost_mult": 0.3, "time_mult": 0.8, "risk_mult": 1.4, "modifier": 1.0},
            {"action": "Automate the Role",
             "description": "Deploy a governed agent for the routine work and hire for the judgment; durable, slower.",
             "cost_mult": 1.4, "time_mult": 2.0, "risk_mult": 0.8, "modifier": 2.5},
        ],
    },
    "TALENT_EXODUS": {
        "severity_mult": 1.5, "depth": 3, "cost_per_node": 4200, "time_per_node": 4,
        "description": "Talent exodus: several key people leave together, concentrating "
                       "knowledge loss on owned capabilities.",
        "options": lambda ctx: [
            {"action": "Retention Counter-Offers",
             "description": f"Targeted counters and re-vesting for the {ctx['agents']} highest-risk owners; "
                            f"fast, precedent risk.",
             "cost_mult": 1.5, "time_mult": 0.4, "risk_mult": 0.7, "modifier": 3.0},
            {"action": "Knowledge Capture Sprint",
             "description": f"Runbook and cross-train across {ctx['caps']} capabilities before departures land; "
                            f"durable, race against the clock.",
             "cost_mult": 0.9, "time_mult": 1.4, "risk_mult": 0.9, "modifier": 3.5},
            {"action": "Rebuild the Bench",
             "description": "Accept the loss and hire/develop a new bench; long ramp, clean slate.",
             "cost_mult": 1.7, "time_mult": 2.6, "risk_mult": 1.2, "modifier": 1.0},
        ],
    },
    "VENDOR_FAILURE": {
        "severity_mult": 1.4, "depth": 3, "cost_per_node": 3100, "time_per_node": 3,
        "description": "Vendor failure: a service/supply provider breaks continuity for "
                       "dependent capabilities.",
        "options": lambda ctx: [
            {"action": "Failover to Backup Vendor",
             "description": f"Cut over the {ctx['count']} dependent entities to a qualified alternate; "
                            f"continuity, switching cost.",
             "cost_mult": 1.3, "time_mult": 0.7, "risk_mult": 0.6, "modifier": 3.5},
            {"action": "Insource Temporarily",
             "description": "Stand the service up in-house as a stopgap; control regained, capacity strain.",
             "cost_mult": 1.6, "time_mult": 1.5, "risk_mult": 1.0, "modifier": 2.0},
            {"action": "Renegotiate + Remediate",
             "description": "Hold the vendor to an SLA-backed recovery plan; cheapest, dependency persists.",
             "cost_mult": 0.6, "time_mult": 1.0, "risk_mult": 1.5, "modifier": 1.0},
        ],
    },
    "BUDGET_CUT": {
        "severity_mult": 1.0, "depth": 3, "cost_per_node": 1250, "time_per_node": 2,
        "description": "Budget reduction: descoping pressure on capabilities and projects.",
        "options": lambda ctx: [
            {"action": "Protect the Core",
             "description": f"Ring-fence the {ctx['caps']} highest-value capabilities, cut the tail; "
                            f"focus-first, opportunity cost.",
             "cost_mult": 0.6, "time_mult": 0.8, "risk_mult": 0.7, "modifier": 3.5},
            {"action": "Efficiency + Automation",
             "description": "Hold scope, cut unit cost via automation and vendor consolidation; durable, slower payoff.",
             "cost_mult": 1.1, "time_mult": 1.6, "risk_mult": 0.9, "modifier": 3.0},
            {"action": "Across-the-Board Trim",
             "description": f"Flat reduction across all {ctx['count']} entities; equitable optics, dilutes everything.",
             "cost_mult": 0.4, "time_mult": 0.5, "risk_mult": 1.6, "modifier": 0.5},
        ],
    },
    "SYSTEM_OUTAGE": {
        "severity_mult": 1.2, "depth": 3, "cost_per_node": 1800, "time_per_node": 1,
        "description": "System outage: availability loss cascading to dependent processes.",
        "options": lambda ctx: [
            {"action": "Failover to Standby",
             "description": f"Redirect the {ctx['count']} dependent entities to the standby region; "
                            f"fast, requires healthy DR.",
             "cost_mult": 1.0, "time_mult": 0.4, "risk_mult": 0.6, "modifier": 4.0},
            {"action": "Root-Cause + Patch",
             "description": "Diagnose and fix forward; durable, longer time-to-restore.",
             "cost_mult": 0.9, "time_mult": 1.4, "risk_mult": 1.0, "modifier": 2.0},
            {"action": "Manual Workaround",
             "description": "Bridge critical processes manually while engineering recovers; cheap, error-prone.",
             "cost_mult": 0.5, "time_mult": 0.7, "risk_mult": 1.5, "modifier": 0.5},
        ],
    },
    "CAPABILITY_LOSS": {
        "severity_mult": 1.6, "depth": 3, "cost_per_node": 3400, "time_per_node": 4,
        "description": "Capability loss: an owned capability degrades or goes offline, "
                       "stalling the processes and agents that depend on it.",
        "options": lambda ctx: [
            {"action": "Rebuild the Capability",
             "description": "Re-staff and re-tool to full strength; complete restoration, real time and cost.",
             "cost_mult": 1.5, "time_mult": 2.0, "risk_mult": 0.6, "modifier": 3.5},
            {"action": "Source Externally",
             "description": f"Contract the capability out to cover the {ctx['count']} dependents; fast, "
                            f"ongoing dependency and margin.",
             "cost_mult": 1.7, "time_mult": 0.6, "risk_mult": 1.0, "modifier": 2.0},
            {"action": "Deprecate + Re-route",
             "description": f"Retire it and re-route work to adjacent capabilities across {ctx['caps']} "
                            f"functions; lean, coverage gaps.",
             "cost_mult": 0.5, "time_mult": 1.0, "risk_mult": 1.5, "modifier": 1.0},
        ],
    },
}

_DEFAULT_PROFILE = {"severity_mult": 1.0, "depth": 3, "cost_per_node": 1250,
                    "time_per_node": 2, "description": "Generic shock.", "options": None}


@router.post("/shock", summary="Inject a shock and run KAEOS evaluation",
             dependencies=[Depends(require_role("operator"))])
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


@router.post("/simulate", summary="Run full demo simulation flow",
             dependencies=[Depends(require_role("operator"))])
async def simulate_flow(tenant_id: str = Depends(get_tenant_id)):
    """Scripted shock for demo purposes — targets the busiest department."""
    nodes, edges = await build_live_twin(tenant_id)
    dept = next((n for n in nodes.values() if n["label"] == "Department"), None)
    target = dept["id"] if dept else "unknown"
    return await inject_shock(
        ShockRequest(shock_type="SYSTEM_OUTAGE", target_id=target), tenant_id
    )
