from app.core.tenant import get_tenant_id
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.database import get_db
from app.models.domain import ProvenanceLedger, Rule

router = APIRouter(prefix="/provenance", tags=["Provenance — L11 Lineage Ledger"])

# The ledger is append-only and unbounded per rule; a read caps at this many
# entries. Full history is available through the CSV export.
_CHAIN_CAP = 500

@router.get("/{rule_id}")
async def get_provenance_chain(rule_id: str, tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    """A rule's hash-chained lineage, newest-capped and tenant-scoped.

    `tenant_id` was accepted here and never applied, so the chain of any rule id
    was readable across tenants. The ledger is append-only with several writers
    (every confidence change, gate decision and agent execution appends), so the
    read is also capped. Fields are listed explicitly rather than returning ORM
    rows, which auto-exposed `actor_hash` and `evidence_ids` and would ship any
    column added later; this matches the shape its two twins already build.
    """
    result = await db.execute(
        select(ProvenanceLedger)
        .where(
            ProvenanceLedger.rule_id == rule_id,
            ProvenanceLedger.tenant_id == tenant_id,
        )
        .order_by(ProvenanceLedger.timestamp.asc())
        .limit(_CHAIN_CAP)
    )
    return {"chain": [
        {
            "id": e.id,
            "event_type": e.event_type,
            "timestamp": e.timestamp.isoformat() if e.timestamp else None,
            "actor_role": e.actor_role,
            "confidence_at": e.confidence_at,
            "reasoning": e.reasoning,
            "chain_hash": e.chain_hash,
        }
        for e in result.scalars().all()
    ]}

@router.get("/global/ledger")
async def get_global_ledger(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    # ProvenanceLedger has no tenant_id column; scope the Rule join to the
    # caller's tenant (in the ON clause) so another tenant's rule_statement is
    # never exposed, while ledger rows with no matching rule are preserved.
    result = await db.execute(
        select(ProvenanceLedger, Rule.statement)
        .outerjoin(Rule, (ProvenanceLedger.rule_id == Rule.id) & (Rule.tenant_id == tenant_id))
        .order_by(ProvenanceLedger.timestamp.desc())
        .limit(100)
    )
    
    ledger = []
    for prov, stmt in result.all():
        entry = prov.__dict__.copy()
        entry.pop('_sa_instance_state', None)
        entry["rule_statement"] = stmt or "Unknown Source/Rule"
        ledger.append(entry)
        
    return {"ledger": ledger}


@router.get("/global/ledger/export")
async def export_global_ledger(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    """Download the Provenance (decision) Ledger as CSV.

    Tenant-safe: scoped via an INNER join to the caller's own rules, so no other
    tenant's ledger rows are exported (stricter than the paged view).
    """
    from app.core.csv_export import csv_response
    result = await db.execute(
        select(
            ProvenanceLedger.id, ProvenanceLedger.rule_id, ProvenanceLedger.event_type,
            ProvenanceLedger.timestamp, Rule.statement.label("rule_statement"),
        )
        .join(Rule, (ProvenanceLedger.rule_id == Rule.id) & (Rule.tenant_id == tenant_id))
        .order_by(ProvenanceLedger.timestamp.desc())
        .limit(50000)
    )
    rows = [dict(m) for m in result.mappings().all()]
    return csv_response(
        rows, "provenance_ledger.csv",
        columns=["id", "rule_id", "event_type", "timestamp", "rule_statement"],
    )


@router.get("/{rule_id}/verify")
async def verify_chain_integrity(rule_id: str, tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    """L11 — Verify tamper-evident integrity of the provenance chain for a rule."""
    from app.services.provenance import ProvenanceEngine
    engine = ProvenanceEngine()
    is_valid = await engine.verify_chain_integrity(db, rule_id)
    return {"rule_id": rule_id, "chain_valid": is_valid, "status": "VERIFIED" if is_valid else "TAMPERED"}
