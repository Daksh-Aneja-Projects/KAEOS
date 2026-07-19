"""
KAEOS — Hash-chained provenance ledger.

A tamper-EVIDENT audit ledger: each event's `chain_hash` is SHA3-512 over
(previous_hash | payload), so any retroactive edit breaks the chain and is
detectable on verification. This is NOT post-quantum cryptography and NOT a
blockchain — there are no lattice signatures, no consensus, and a database
owner can still rewrite rows (the chain makes that *detectable*, not
*impossible*). Named "quantum ledger" historically; the guarantee it provides
is tamper-evidence via hash chaining.
"""
import logging
import hashlib
import json
from datetime import datetime, timezone
import uuid

from sqlalchemy.ext.asyncio import AsyncSession
from app.models.domain import ProvenanceLedger

logger = logging.getLogger(__name__)


class QuantumLedgerEngine:
    """Append-only, hash-chained provenance ledger (SHA3-512 tamper-evidence)."""

    # Domain-separation constant mixed into every hash.
    _CHAIN_DOMAIN = "kaeos.provenance.chain.v1"

    @staticmethod
    def _chain_hash(payload: dict, previous_hash: str) -> str:
        """SHA3-512 over (domain | previous_hash | canonical_payload).

        Links each entry to its predecessor so the chain is tamper-evident.
        """
        data_str = json.dumps(payload, sort_keys=True)
        combined = f"{QuantumLedgerEngine._CHAIN_DOMAIN}|{previous_hash}|{data_str}"
        return hashlib.sha3_512(combined.encode()).hexdigest()

    @staticmethod
    async def record_quantum_event(db: AsyncSession, event_type: str, actor: str, reasoning: str, payload: dict) -> ProvenanceLedger:
        """Append a hash-chained event to the provenance ledger."""
        logger.info(f"Writing event to provenance ledger: {event_type} by {actor}")

        from sqlalchemy import select, desc

        # Fetch the latest block so this entry links to it (chain continuity).
        last_entry_q = await db.execute(
            select(ProvenanceLedger)
            .order_by(desc(ProvenanceLedger.timestamp))
            .limit(1)
        )
        last_entry = last_entry_q.scalar_one_or_none()

        if last_entry and last_entry.chain_hash:
            actual_prev_hash = last_entry.chain_hash
        else:
            # First event in the entire system becomes the genesis block.
            actual_prev_hash = hashlib.sha3_512(b"genesis_block").hexdigest()

        chain_hash = QuantumLedgerEngine._chain_hash(payload, actual_prev_hash)

        payload_str = json.dumps(payload, sort_keys=True)

        # Tenant travels in the event payload when the caller sets it; otherwise
        # fall back to the ambient request tenant. This MUST be populated: on
        # Postgres the provenance_ledger RLS policy binds app.tenant_id from the
        # same contextvar, so a NULL tenant_id (payload without it) is rejected
        # with an InsufficientPrivilegeError and 500s the whole request.
        _tenant = payload.get("tenant_id")
        if not _tenant:
            try:
                from app.core.context import current_tenant_id
                _tenant = current_tenant_id.get()
            except Exception:
                _tenant = None

        entry = ProvenanceLedger(
            id=str(uuid.uuid4()),
            tenant_id=_tenant,
            rule_id=payload.get("rule_id"),
            event_type=event_type,
            timestamp=datetime.now(timezone.utc),
            actor_role=actor,
            confidence_at=payload.get("confidence", 1.0),
            reasoning=f"{reasoning} | PAYLOAD: {payload_str}",
            chain_hash=chain_hash,
        )

        db.add(entry)
        await db.commit()

        logger.info(f"Recorded ledger event; chain hash: {chain_hash[:32]}...")
        return entry
