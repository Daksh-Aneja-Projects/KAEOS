"""
KAEOS Enterprise State Service
Phase 2: Enterprise State Engine
Handles state mutations, snapshots, and querying for the Enterprise Twin.
"""

import logging
from typing import Dict, Any, Optional
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

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
        Applies mutations to the current state and creates a new snapshot if necessary,
        or updates the current one in place.
        """
        model = StateService._get_model_for_domain(domain)
        if not model:
            raise ValueError(f"Unknown domain for state engine: {domain}")
            
        current_state = await StateService.get_state(db, tenant_id, domain)
        
        if not current_state:
            # Create initial state
            new_state = model(tenant_id=tenant_id, **mutations)
            db.add(new_state)
            await db.commit()
            await db.refresh(new_state)
            logger.info(f"Initialized {domain} state for {tenant_id}")
            return new_state
            
        # For full historical tracking, we would insert a new row.
        # For now, we update in-place to keep it simple.
        for key, value in mutations.items():
            if hasattr(current_state, key):
                setattr(current_state, key, value)
                
        current_state.updated_at = datetime.now(timezone.utc)
        db.add(current_state)
        await db.commit()
        await db.refresh(current_state)
        
        logger.info(f"Mutated {domain} state for {tenant_id}: {mutations}")
        return current_state

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
