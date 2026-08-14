"""
KAEOS Lending Domain - Adverse Action Agent

Generates a compliant ECOA/Reg B adverse-action notice for a denial. The notice
content is built deterministically from the persisted denial reasons and
validated against the ECOA checker before it is issued (fail-closed) - see
app/lending/services/underwriting.generate_adverse_action.
"""
import logging
from typing import Any, Dict

from sqlalchemy.ext.asyncio import AsyncSession

from app.lending.services.underwriting import generate_adverse_action

logger = logging.getLogger(__name__)


class AdverseActionAgent:
    def __init__(self):
        self.persona = "You are the KAEOS Adverse Action Agent."

    async def issue(self, db: AsyncSession, application_id: str, tenant_id: str, *,
                    issued_by: str) -> Dict[str, Any]:
        notice = await generate_adverse_action(
            db, tenant_id, application_id=application_id, decided_by=issued_by)
        return {
            "status": "issued",
            "notice_id": notice.id,
            "application_id": application_id,
            "specific_reasons": notice.specific_reasons,
            "within_30_days": notice.within_30_days,
            "body": notice.body,
        }
