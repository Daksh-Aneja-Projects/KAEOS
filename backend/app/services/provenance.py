import json
import hashlib
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession

class ProvenanceEngine:
    """L11 - Knowledge Provenance & Lineage Ledger"""
    
    @staticmethod
    def calculate_chain_hash(parent_hash: str, payload: dict) -> str:
        """Calculate tamper-evident hash for the provenance chain."""
        content = f"{parent_hash}|{json.dumps(payload, sort_keys=True)}"
        return hashlib.sha256(content.encode('utf-8')).hexdigest()

    async def log_event(
        self,
        db_session: AsyncSession,
        rule_id: UUID,
        event_type: str,
        actor_hash: str,
        actor_role: str,
        evidence_ids: list[UUID],
        confidence_at: float,
        reasoning: str,
        parent_id: UUID = None,
        tenant_id: str = None,
    ) -> str:
        """Appends an immutable event to the provenance ledger.

        tenant_id scopes the entry. If a caller doesn't pass it, we resolve it
        from the subject rule so the row is never left unattributed when it can
        be avoided (older callers predate the column).
        """
        from app.models.domain import ProvenanceLedger, Rule
        import uuid

        # 1. Fetch parent hash if parent_id is provided
        parent_hash = "GENESIS"
        if parent_id:
            parent_record = await db_session.get(ProvenanceLedger, str(parent_id))
            if parent_record:
                parent_hash = parent_record.chain_hash

        if tenant_id is None:
            # Best-effort backfill from the subject rule (rule-event entries).
            rule = await db_session.get(Rule, str(rule_id))
            tenant_id = getattr(rule, "tenant_id", None)
            
        payload = {
            "rule_id": str(rule_id),
            "event_type": event_type,
            "actor_hash": actor_hash,
            "evidence_ids": [str(e) for e in evidence_ids],
            "confidence_at": confidence_at,
            "reasoning": reasoning
        }
        
        chain_hash = self.calculate_chain_hash(parent_hash, payload)
        
        # Create record
        new_record = ProvenanceLedger(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            rule_id=str(rule_id),
            event_type=event_type,
            actor_hash=actor_hash,
            actor_role=actor_role,
            evidence_ids=[str(e) for e in evidence_ids],
            confidence_at=confidence_at,
            reasoning=reasoning,
            parent_id=str(parent_id) if parent_id else None,
            chain_hash=chain_hash
        )
        db_session.add(new_record)
        await db_session.commit()
        
        return chain_hash

    async def verify_chain_integrity(self, db_session: AsyncSession, rule_id: UUID) -> bool:
        """Verifies that the chain has not been tampered with."""
        from sqlalchemy import select
        from app.models.domain import ProvenanceLedger
        
        # Fetch all records for the rule, ordered by timestamp
        q = await db_session.execute(
            select(ProvenanceLedger)
            .where(ProvenanceLedger.rule_id == str(rule_id))
            .order_by(ProvenanceLedger.timestamp)
        )
        records = q.scalars().all()
        
        if not records:
            return True
            
        # Traverse from genesis to leaf checking hashes
        for record in records:
            parent_hash = "GENESIS"
            if record.parent_id:
                parent_q = await db_session.execute(select(ProvenanceLedger).where(ProvenanceLedger.id == record.parent_id))
                parent_rec = parent_q.scalar_one_or_none()
                if parent_rec:
                    parent_hash = parent_rec.chain_hash
                    
            payload = {
                "rule_id": record.rule_id,
                "event_type": record.event_type,
                "actor_hash": record.actor_hash,
                "evidence_ids": record.evidence_ids,
                "confidence_at": record.confidence_at,
                "reasoning": record.reasoning
            }
            calculated_hash = self.calculate_chain_hash(parent_hash, payload)
            if calculated_hash != record.chain_hash:
                return False
                
        return True
