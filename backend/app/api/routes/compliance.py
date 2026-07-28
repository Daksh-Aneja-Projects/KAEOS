"""KAEOS — Compliance controls evidence API.

Exposes the audit-readiness controls inventory (SOC 2 / ISO 27001 / GDPR / SOX
mapping with code+test evidence). Read-only; intended for an operator preparing
for a third-party audit. See app/services/compliance_controls.py for the honest
boundary: this is evidence, not a certificate.
"""
from fastapi import APIRouter, Depends

from app.core.tenant import get_tenant_id
from app.services import compliance_controls

router = APIRouter(prefix="/compliance", tags=["Compliance"])


@router.get("/controls")
async def get_controls_report(_tenant_id: str = Depends(get_tenant_id)):
    """Return the implemented-controls evidence report and framework coverage."""
    return compliance_controls.build_controls_report()
