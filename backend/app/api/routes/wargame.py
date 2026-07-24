"""Autonomy Wargaming API (v4 IP-4)."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.tenant import get_tenant_id
from app.services.wargame import run_wargame, list_playbooks

router = APIRouter(prefix="/wargame", tags=["Wargaming"])


class WargameIn(BaseModel):
    playbook: str = "cyber_cascade"
    custom: Optional[list] = None   # optional [[shock, dept, severity], ...]


@router.get("/playbooks")
async def playbooks():
    """The adversarial cascades available to run."""
    return await list_playbooks()


@router.post("/run")
async def run(
    body: WargameIn,
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """Run an adversarial cascade against the twin and score resilience + the
    agents' safe response under compounding stress."""
    custom = None
    if body.custom:
        try:
            custom = [(str(s[0]), str(s[1]), int(s[2])) for s in body.custom]
        except Exception:
            raise HTTPException(status_code=400, detail="custom must be [[shock, dept, severity], ...]")
    res = await run_wargame(db, tenant_id, playbook=body.playbook, custom=custom)
    if res.get("error"):
        raise HTTPException(status_code=404, detail=res["error"])
    return res
