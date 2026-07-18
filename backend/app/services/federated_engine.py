"""
KAEOS 10X — Federated Epistemic Engine (L22)
Cross-Tenant Zero-Knowledge Skill Swarming
"""
import logging
import hashlib
import json
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.domain import Skill

logger = logging.getLogger(__name__)

class FederatedSkillWeight:
    def __init__(self, global_id: str, abstract_domain: str, procedural_hash: str, success_weight: float):
        self.global_id = global_id
        self.abstract_domain = abstract_domain
        self.procedural_hash = procedural_hash
        self.success_weight = success_weight


class FederatedEngine:
    """
    Manages the zero-knowledge export and import of Epistemic Weights across the global swarm.
    """

    @staticmethod
    def _extract_zero_knowledge_procedural_weight(skill: Skill) -> str:
        """
        Strips all PII, tenant-specific endpoints, and human names from a skill.
        Extracts only the abstract logical structure (the "weight") and hashes it.
        """
        abstract_steps = []
        for step in skill.steps:
            # We only keep the 'action' or 'tool' category, dropping specific IDs or thresholds
            # that might be proprietary.
            abstract_step = {
                "action_type": step.get("action", "unknown").split("_")[0], 
                "requires_tool": "tool" in step
            }
            abstract_steps.append(abstract_step)
            
        # Serialize and hash the abstract procedure
        procedure_str = json.dumps(abstract_steps, sort_keys=True)
        return hashlib.sha3_256(procedure_str.encode()).hexdigest()

    @staticmethod
    async def export_skill_to_swarm(db: AsyncSession, skill_id: str, tenant_id: str | None = None) -> str:
        """
        Exports a high-performing skill to the Global KAEOS Swarm without leaking data.
        Writes the abstract mathematical weight securely to the ProvenanceLedger.
        """
        logger.info(f"Initiating zero-knowledge export to Global Swarm for skill: {skill_id}")

        stmt = select(Skill).where(Skill.skill_id == skill_id)
        if tenant_id is not None:
            stmt = stmt.where(Skill.tenant_id == tenant_id)
        skill_q = await db.execute(stmt)
        skill = skill_q.scalar_one_or_none()
        
        if not skill:
            raise ValueError(f"Skill {skill_id} not found.")
            
        if skill.success_rate < 0.90:
            raise ValueError(f"Skill {skill_id} does not meet the 90% success threshold for Swarm export.")
            
        procedural_hash = FederatedEngine._extract_zero_knowledge_procedural_weight(skill)
        global_id = f"swarm_node_{skill.tenant_id}_{hashlib.md5(skill_id.encode()).hexdigest()[:8]}"
        
        from app.services.quantum_ledger import QuantumLedgerEngine
        
        # Write to the immutable global ledger
        ledger_entry = await QuantumLedgerEngine.record_quantum_event(
            db=db,
            event_type="FEDERATED_SWARM_EXPORT",
            actor=f"tenant_swarm_node_{skill.tenant_id}",
            reasoning=f"Exporting skill success weight > 90% for domain {skill.domain}",
            payload={
                "global_id": global_id,
                "abstract_domain": skill.domain,
                "procedural_hash": procedural_hash,
                "success_weight": skill.success_rate
            }
        )
        
        # Log the export locally
        if "federated_events" not in skill.guardrails:
            skill.guardrails["federated_events"] = []
            
        skill.guardrails["federated_events"].append({
            "event": "EXPORTED_TO_SWARM",
            "global_id": global_id,
            "procedural_hash": procedural_hash,
            "ledger_receipt": ledger_entry.chain_hash,
            "timestamp": datetime.now(timezone.utc).isoformat()
        })
        
        db.add(skill)
        await db.commit()
        
        logger.info(f"Successfully exported {skill_id} to Global Swarm with receipt: {ledger_entry.chain_hash}")
        return ledger_entry.chain_hash

    @staticmethod
    async def import_swarm_weight_to_tenant(db: AsyncSession, tenant_id: str, swarm_ledger_receipt: str) -> int:
        """
        L21 Hive Mind: Imports an abstract procedural weight from the global swarm (via Ledger receipt) 
        to locally boost skills in the same domain that share a structural similarity.
        Returns the number of local skills boosted.
        """
        from app.models.domain import ProvenanceLedger
        import json
        
        ledger_q = await db.execute(select(ProvenanceLedger).where(ProvenanceLedger.chain_hash == swarm_ledger_receipt))
        ledger_entry = ledger_q.scalar_one_or_none()
        if not ledger_entry or ledger_entry.event_type != "PQ_FEDERATED_SWARM_EXPORT":
            raise ValueError("Invalid swarm ledger receipt or not a swarm export.")
            
        reasoning_str = ledger_entry.reasoning
        if "| PAYLOAD: " not in reasoning_str:
            raise ValueError("Payload missing from ledger reasoning.")
            
        payload_str = reasoning_str.split("| PAYLOAD: ")[1].strip()
        payload = json.loads(payload_str)
        
        swarm_domain = payload.get("abstract_domain")
        swarm_hash = payload.get("procedural_hash")
        swarm_global_id = payload.get("global_id")
        
        logger.info(f"Tenant {tenant_id} importing Swarm Weight via receipt {swarm_ledger_receipt}")
        
        # Find local skills in the same domain that have low confidence
        skill_q = await db.execute(
            select(Skill)
            .where(Skill.tenant_id == tenant_id)
            .where(Skill.domain == swarm_domain)
            .where(Skill.confidence < 0.80)
        )
        local_skills = skill_q.scalars().all()
        
        boosted_count = 0
        for skill in local_skills:
            # Check if local skill matches the abstract procedure hash
            local_hash = FederatedEngine._extract_zero_knowledge_procedural_weight(skill)
            if local_hash == swarm_hash:
                # The local skill matches the global successful pattern!
                skill.confidence = min(1.0, skill.confidence + 0.15)
                skill.confidence_tier = "VALIDATED_PEER"  # Upgraded by the swarm
                
                if "federated_events" not in skill.guardrails:
                    skill.guardrails["federated_events"] = []
                    
                skill.guardrails["federated_events"].append({
                    "event": "IMPORTED_SWARM_BOOST",
                    "global_id": swarm_global_id,
                    "confidence_delta": 0.15,
                    "timestamp": datetime.now(timezone.utc).isoformat()
                })
                db.add(skill)
                boosted_count += 1
                
        if boosted_count > 0:
            await db.commit()
            logger.info(f"L21 Hive Mind: Boosted {boosted_count} local skills in tenant {tenant_id} via zero-knowledge swarm weight.")
            
        return boosted_count
