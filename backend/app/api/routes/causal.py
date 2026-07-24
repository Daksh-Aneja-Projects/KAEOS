"""Causal Discovery API (v4 IP-6)."""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.tenant import get_tenant_id
from app.services.causal import discover

router = APIRouter(prefix="/causal", tags=["Causal Discovery"])


@router.get("/discover")
async def discover_causal(
    days: int = 45,
    min_strength: float = 0.4,
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """Discover likely causal links between departments from real adverse-event
    series (lagged cross-correlation). Honest about thin data."""
    return await discover(db, tenant_id, days=max(7, min(365, days)),
                          min_strength=max(0.1, min(0.95, min_strength)))
