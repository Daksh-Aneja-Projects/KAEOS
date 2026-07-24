"""Enterprise Time Machine API (v4 IP-3)."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.tenant import get_tenant_id, require_role
from app.services import time_machine

router = APIRouter(prefix="/time-machine", tags=["Time Machine"])


class CounterfactualIn(BaseModel):
    execution_id: str
    flip: str  # approve | fail | escalate
    days: int = 45


@router.get("/timeline")
async def get_timeline(
    days: int = Query(45, ge=1, le=365),
    limit: int = Query(200, ge=1, le=1000),
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """The real decision history with each decision's classification + the current
    reconstructed north-star."""
    return await time_machine.timeline(db, tenant_id, days=days, limit=limit)


@router.get("/state")
async def get_state(
    at: str,
    days: int = Query(45, ge=1, le=365),
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """The reconstructed enterprise state (north-star + distribution) as of a
    point in time — everything up to `at`."""
    res = await time_machine.state_as_of(db, tenant_id, at=at, days=days)
    if res.get("error"):
        raise HTTPException(status_code=400, detail=res["error"])
    return res


@router.post("/counterfactual")
async def post_counterfactual(
    body: CounterfactualIn,
    tenant: dict = Depends(require_role("operator")),
    db: AsyncSession = Depends(get_db),
):
    """Recompute the north-star with one historical decision flipped. Role-gated
    like the other simulation endpoints."""
    if body.flip not in ("approve", "fail", "escalate"):
        raise HTTPException(status_code=400, detail="flip must be approve|fail|escalate")
    res = await time_machine.counterfactual(
        db, tenant["tenant_id"], execution_id=body.execution_id, flip=body.flip,
        days=max(1, min(365, body.days)))
    if res.get("error"):
        raise HTTPException(status_code=404, detail=res["error"])
    return res
