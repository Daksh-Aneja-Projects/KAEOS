"""KAEOS 10X — Regulatory & Quantum APIs"""
from app.core.tenant import get_tenant_id, require_role
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel

from app.core.database import get_db
from app.services.regulatory_engine import RegulatoryEngine, RegulatoryUpdate
from app.services.quantum_ledger import QuantumLedgerEngine

router = APIRouter(prefix="/10x", tags=["KAEOS 10X — Advanced Capabilities"])

class RegulationPayload(BaseModel):
    framework_name: str
    directive_text: str
    urgency: str

@router.post("/ingest-regulation")
async def ingest_regulation(payload: RegulationPayload, tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db)):
    """
    Ingests a new legal framework and autonomously generates compliance rules. Requires operator role.
    """
    tenant_id = tenant["tenant_id"]
    try:
        update = RegulatoryUpdate(
            framework_name=payload.framework_name,
            directive_text=payload.directive_text,
            urgency=payload.urgency
        )
        # Write the synthesized rules under the caller's tenant, not a global "default".
        result = await RegulatoryEngine.ingest_new_regulation(db, update, tenant_id=tenant_id)
        
        # Also log this massive event in the Quantum Ledger
        await QuantumLedgerEngine.record_quantum_event(
            db=db,
            event_type="REGULATORY_AUTO_PATCH",
            actor="SYSTEM_L24",
            reasoning=f"Autonomously ingested and complied with {update.framework_name}",
            payload=result
        )
        
        return result
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Regulation ingestion failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

from sqlalchemy import select
from app.models.domain import ProvenanceLedger, Rule, Skill

@router.get("/quantum-events")
async def get_quantum_events(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    """Fetch recent hash-chained (tamper-evident) provenance ledger events."""
    # Scoped to the caller's tenant (defense in depth alongside Postgres RLS);
    # chain_hash IS NOT NULL selects the hash-chained entries.
    q = await db.execute(
        select(ProvenanceLedger)
        .filter(ProvenanceLedger.tenant_id == tenant_id, ProvenanceLedger.chain_hash.isnot(None))
        .order_by(ProvenanceLedger.timestamp.desc())
        .limit(100)
    )
    events = q.scalars().all()
    return [{"id": e.id, "event_type": e.event_type, "timestamp": e.timestamp, "reasoning": e.reasoning, "chain_hash": e.chain_hash} for e in events]

@router.get("/regulatory-rules")
async def get_regulatory_rules(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    """Fetch all automatically synthesized regulatory rules."""
    # Scoped to the caller's tenant.
    q = await db.execute(select(Rule).filter(Rule.tenant_id == tenant_id, Rule.workflow_id == "wf_compliance_auto"))
    rules = q.scalars().all()
    return [{"id": r.id, "statement": r.statement, "compliance_tags": r.compliance_tags, "domain": r.domain, "created_at": r.created_at} for r in rules]

@router.get("/federated-exports")
async def get_federated_exports(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    """Fetch all skills exported to the global swarm."""
    # Scoped to the caller's tenant.
    q = await db.execute(select(Skill).where(Skill.tenant_id == tenant_id))
    skills = q.scalars().all()
    exports = []
    for s in skills:
        events = s.guardrails.get("federated_events", [])
        for ev in events:
            exports.append({
                "skill_id": s.skill_id,
                "domain": s.domain,
                "global_id": ev.get("global_id"),
                "procedural_hash": ev.get("procedural_hash"),
                "timestamp": ev.get("timestamp"),
                "success_rate": s.success_rate
            })
    return exports

@router.get("/polymorphic-events")
async def get_polymorphic_events(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    """Fetch all code generation events from the polymorphic engine."""
    # Scoped to the caller's tenant.
    q = await db.execute(select(Skill).where(Skill.tenant_id == tenant_id))
    skills = q.scalars().all()
    poly_events = []
    for s in skills:
        events = s.guardrails.get("polymorphic_events", [])
        for ev in events:
            poly_events.append({
                "skill_id": s.skill_id,
                "tool": ev.get("tool"),
                "event_type": ev.get("event"),
                "timestamp": ev.get("timestamp")
            })
    return poly_events

@router.post("/precog/force-cycle")
async def force_precog_cycle(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    """Manually trigger the L24 Pre-Cog Engine."""
    from app.services.precog_engine import PreCogEngine
    engine = PreCogEngine()
    # Scope signal detection and rule decay to the caller's tenant.
    signals = await engine._monitor_external_signals(db, tenant_id=tenant_id)
    if not signals:
        return {"status": "IDLE", "message": "No new macro signals detected."}

    # Process the first signal found
    await engine._recalculate_active_bids(db, signals[0], tenant_id=tenant_id)
    return {"status": "PROCESSED", "signal": signals[0]["summary"]}

class PhysicsSimRequest(BaseModel):
    shock_type: str = "MACRO_RATE_HIKE_50BPS"


@router.post("/physics/simulate")
async def trigger_physics_simulation(
    payload: PhysicsSimRequest | None = None,
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """Trigger the Enterprise Physics Engine for causal chain modeling.

    Accepts any shock in MACRO_SHOCKS: MACRO_RATE_HIKE_50BPS,
    SUPPLY_CHAIN_DISRUPTION, TALENT_EXODUS, BUDGET_CUT, MERGER_INTEGRATION,
    CYBER_INCIDENT.
    """
    from app.services.enterprise_physics_engine import EnterprisePhysicsEngine, MACRO_SHOCKS
    shock = (payload.shock_type if payload else "MACRO_RATE_HIKE_50BPS").upper()
    if shock not in MACRO_SHOCKS:
        raise HTTPException(400, f"Unknown shock_type. Supported: {sorted(MACRO_SHOCKS)}")

    engine = EnterprisePhysicsEngine()
    nodes_affected = await engine.simulate_impact(db, shock)
    return {
        "status": "SIMULATION_COMPLETE",
        "shock_type": shock,
        "nodes_affected": len(nodes_affected),
        "ripple_effect": nodes_affected
    }
