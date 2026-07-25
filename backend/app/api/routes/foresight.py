"""KAEOS Foresight API — the autonomous, prescriptive reality lane.

Shock / What-if / Wargame / Replay are reactive: a human poses a premise. These
endpoints run without a prompt and hand back a ranked, actionable board:

  GET  /foresight/premortem   — scenarios ranked by exposure; the uncovered ones
                                are the "Inevitable Surprises"
  GET  /foresight/trajectory  — what KAEOS will do autonomously over 30/60/90d,
                                the safe-autonomy north star, and where a human
                                is still required
  POST /foresight/commission  — draft a mission that closes one scenario's gap.
                                DRAFTED, never executed: it lands in the normal
                                mission flow for a human to approve.
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.tenant import get_tenant_id, require_role
from app.services import foresight as foresight_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/foresight", tags=["KAEOS Foresight"])


@router.get("/premortem", summary="Rank latent scenarios by exposure (Pre-Mortem Radar)")
async def get_premortem(
    signal_days: int = Query(90, ge=7, le=365),
    limit: int = Query(8, ge=1, le=20),
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """exposure = likelihood x blast_radius x preparedness_gap, over the live twin."""
    return await foresight_service.premortem_radar(
        db, tenant_id, signal_days=signal_days, limit=limit
    )


@router.get("/trajectory", summary="Projected autonomous trajectory + decision points")
async def get_trajectory(
    days: int = Query(45, ge=7, le=365),
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    return await foresight_service.prescriptive_trajectory(db, tenant_id, days=days)


class CommissionIn(BaseModel):
    scenario: str
    goal: str | None = None
    narrative: str | None = None


@router.post("/commission", summary="Draft a mission that closes a scenario's gap",
             dependencies=[Depends(require_role("operator"))])
async def commission_gap_closer(
    body: CommissionIn,
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """Create the gap-closing mission in PLANNING — a human approves before it runs.

    Deliberately NOT auto-executed: Foresight proposes, a human commissions. The
    mission enters the same governed flow as any other (planning -> approval ->
    gated steps), so nothing here bypasses the autonomy dial or HITL.
    """
    scenario = (body.scenario or "").strip().upper()
    if not scenario:
        raise HTTPException(status_code=400, detail="scenario is required")

    # Re-derive the draft server-side: a client must not be able to dictate the
    # narrative attached to a governed mission.
    report = await foresight_service.premortem_radar(db, tenant_id, limit=50)
    match = next((s for s in report["scenarios"] if s["scenario"] == scenario), None)
    if match is None:
        raise HTTPException(status_code=404, detail=f"unknown scenario {scenario}")

    draft = match["recommended_mission"]
    goal = (body.goal or draft["goal"]).strip()

    from app.models.missions import Mission

    mission = Mission(
        tenant_id=tenant_id,
        goal=goal,
        narrative=(body.narrative or draft["narrative"]),
        status="PLANNING",
        created_by="foresight",
        departments=[],
    )
    db.add(mission)
    await db.commit()
    await db.refresh(mission)

    logger.info("[Foresight] commissioned gap-closer mission %s for %s", mission.id, scenario)
    return {
        "mission_id": mission.id,
        "scenario": scenario,
        "goal": mission.goal,
        "status": mission.status,
        "exposure_at_commission": match["exposure"],
        "note": "Drafted in PLANNING. A human must approve it before anything runs.",
    }
