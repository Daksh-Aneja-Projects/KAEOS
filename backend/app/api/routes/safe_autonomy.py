"""Safe Autonomy Rate - the north-star metric, exposed for the executive view."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.tenant import get_tenant_id
from app.services.safe_autonomy import compute_safe_autonomy

router = APIRouter(prefix="/metrics", tags=["Metrics"])


@router.get("/safe-autonomy")
async def get_safe_autonomy(
    days: int = Query(30, ge=1, le=365),
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """Safe-autonomy-rate with its explainable breakdown, per-skill split, and
    daily time-series. Computed live from logged executions for this tenant."""
    return await compute_safe_autonomy(db, tenant_id, days=days)
