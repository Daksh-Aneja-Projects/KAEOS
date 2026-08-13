"""
KAEOS — Hash-chained provenance ledger (event-stream facade).

Historically named the "quantum ledger"; the guarantee it provides is
tamper-evidence via a signed hash chain, NOT post-quantum cryptography and NOT
a blockchain.

This module is now a facade over the unified ledger writer
(`app/services/provenance.py`, schema v2). The pre-unification implementation
derived each entry's parent from the newest row by WALL-CLOCK TIMESTAMP across
ALL tenants: concurrent writes or clock skew silently forked the chain, the
parent was never persisted, and there was no verifier. The unified writer
stores an explicit parent id, scopes chains per tenant, serializes appends via
database uniqueness (safe across workers and replicas), signs entries with an
HMAC key, and is covered by `verify_chain`.
"""
import json
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import ProvenanceLedger
from app.services.provenance import append_ledger_event

logger = logging.getLogger(__name__)


class QuantumLedgerEngine:
    """Append-only, signed, hash-chained provenance ledger (unified v2)."""

    @staticmethod
    async def record_quantum_event(
        db: AsyncSession, event_type: str, actor: str, reasoning: str, payload: dict
    ) -> ProvenanceLedger:
        """Append a signed event to the tenant's provenance event stream."""
        logger.info(f"Writing event to provenance ledger: {event_type} by {actor}")

        # Tenant travels in the event payload when the caller sets it; otherwise
        # fall back to the ambient request tenant. This MUST be populated: on
        # Postgres the provenance_ledger RLS policy binds app.tenant_id from the
        # same contextvar, so an unattributed row is rejected outright.
        tenant = payload.get("tenant_id")
        if not tenant:
            try:
                from app.core.context import current_tenant_id
                tenant = current_tenant_id.get()
            except LookupError:
                tenant = None

        payload_str = json.dumps(payload, sort_keys=True)
        entry = await append_ledger_event(
            db,
            tenant_id=tenant,
            rule_id=payload.get("rule_id"),
            event_type=event_type,
            actor_role=actor,
            confidence_at=payload.get("confidence", 1.0),
            reasoning=f"{reasoning} | PAYLOAD: {payload_str}",
        )
        logger.info(f"Recorded ledger event; chain hash: {entry.chain_hash[:32]}...")
        return entry
