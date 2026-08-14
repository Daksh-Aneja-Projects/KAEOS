"""KAEOS - deterministic compliance checker surface.

The honest answer to "which compliance claims can this platform actually
verify, and does THIS action pass?" - backed by the deterministic statutory
checker registry (no LLM), one governance spine across every department.
"""
from typing import List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.core.tenant import get_tenant_id

router = APIRouter(prefix="/compliance", tags=["Governance - Compliance"])


@router.get("/frameworks")
async def list_supported_frameworks(tenant_id: str = Depends(get_tenant_id)):
    """Every framework the platform can DETERMINISTICALLY verify, with the
    statute each cites and the department it belongs to. A tag not listed here
    is not a real control - the /check endpoint returns UNBACKED for it."""
    from app.compliance.registry import list_frameworks
    frameworks = list_frameworks()
    return {"count": len(frameworks), "frameworks": frameworks,
            "note": "Deterministic statutory checkers. Tags absent here are not "
                    "verified and fail closed at /check."}


class ComplianceCheckIn(BaseModel):
    frameworks: List[str]
    context: Optional[dict] = None


@router.post("/check")
async def run_compliance_check(body: ComplianceCheckIn, tenant_id: str = Depends(get_tenant_id)):
    """Run the requested frameworks' deterministic checkers against a context.
    Fail-closed: a framework with no backing checker returns UNBACKED (which is
    blocking), so an unbacked compliance claim never reads as satisfied."""
    from app.compliance.registry import run_checks
    return run_checks(body.frameworks, body.context or {})
