"""
KAEOS Enterprise State Service
Phase 2: Enterprise State Engine
Handles state mutations, snapshots, and querying for the Enterprise Twin.
"""

import logging
from typing import Dict, Any, Optional
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import inspect as sa_inspect, select

from app.models.enterprise_state import FinanceState, HRState, OpsState, ITState

logger = logging.getLogger(__name__)


class StateService:
    
    @staticmethod
    async def get_state(db: AsyncSession, tenant_id: str, domain: str) -> Optional[Any]:
        """Fetch the current state for a given domain."""
        model = StateService._get_model_for_domain(domain)
        if not model:
            return None
            
        q = await db.execute(select(model).where(model.tenant_id == tenant_id).order_by(model.snapshot_at.desc()).limit(1))
        return q.scalar_one_or_none()

    @staticmethod
    async def mutate_state(db: AsyncSession, tenant_id: str, domain: str, mutations: Dict[str, Any]) -> Any:
        """
        Append a NEW state snapshot for the tenant/domain.

        The Enterprise Twin is a time-series: each mutation inserts a fresh row
        (prior column values carried forward, then the mutations applied, with a
        new ``snapshot_at``) instead of overwriting the current one. This
        preserves full history — ``get_state`` returns the most recent snapshot,
        and older rows remain queryable for trends/audit. (Requires the
        non-unique ``tenant_id`` index from migration 0006.)
        """
        model = StateService._get_model_for_domain(domain)
        if not model:
            raise ValueError(f"Unknown domain for state engine: {domain}")

        current_state = await StateService.get_state(db, tenant_id, domain)

        if not current_state:
            new_state = model(tenant_id=tenant_id, **mutations)
            db.add(new_state)
            await db.commit()
            await db.refresh(new_state)
            logger.info(f"Initialized {domain} state for {tenant_id}")
            return new_state

        # Carry prior values forward into a new snapshot row. Drop the identity
        # and timestamp columns so their defaults generate a fresh id/snapshot_at.
        columns = {c.key for c in sa_inspect(model).columns}
        carried = {
            k: getattr(current_state, k)
            for k in columns
            if k not in ("id", "snapshot_at", "updated_at")
        }
        carried.update({k: v for k, v in mutations.items() if k in columns})

        new_snapshot = model(**carried)
        db.add(new_snapshot)
        await db.commit()
        await db.refresh(new_snapshot)

        logger.info(f"Snapshotted {domain} state for {tenant_id}: {mutations}")
        return new_snapshot

    @staticmethod
    def _get_model_for_domain(domain: str):
        mapping = {
            "hr": HRState,
            "finance": FinanceState,
            "operations": OpsState,
            "it": ITState,
            "engineering": ITState
        }
        return mapping.get(domain.lower())
