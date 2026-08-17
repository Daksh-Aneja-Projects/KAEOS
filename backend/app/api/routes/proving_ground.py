"""Governance Proving Ground — the Assurance Score (gate catch-rate).

Read-only governance evidence: any authenticated user may see whether the gates
actually stop known-bad actions. The battery is deterministic and tenant-agnostic
(it fires the same global gate logic regardless of tenant data), so it is cheap
and carries no tenant PII.
"""
import asyncio

from fastapi import APIRouter, Depends

from app.core.tenant import require_role
from app.services.proving_ground import BATTERY_VERSION, build_battery, run_battery

router = APIRouter(prefix="/proving-ground", tags=["Proving Ground"])


@router.get("/scenarios")
async def scenarios(_tenant: dict = Depends(require_role("viewer"))):
    """The versioned battery of known-bad actions (catalog, not fired)."""
    return {
        "battery_version": BATTERY_VERSION,
        "scenarios": [
            {"id": a.id, "name": a.name, "category": a.category,
             "department": a.department, "severity": a.severity, "gate": a.gate}
            for a in build_battery()
        ],
    }


@router.get("/run")
async def run(_tenant: dict = Depends(require_role("viewer"))):
    """Fire the battery through the LIVE gates and return the Assurance Score plus
    the per-attack catch grid. A gate that regresses lets its attack escape and
    the score drops below 1.0."""
    # Pure CPU (deterministic checkers + regex guard, no LLM) but offloaded so a
    # future heavier battery never blocks the event loop.
    return await asyncio.to_thread(run_battery)
