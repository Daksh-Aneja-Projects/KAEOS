"""
KAEOS Finance Domain — Audit Agent

SOX control testing automation, finding tracking, and continuous monitoring.
"""
import logging
from typing import Dict, Any, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.finance.models.audit import AuditFinding, FindingStatus
from app.finance.models.compliance import SOXControl, SOXControlStatus

logger = logging.getLogger(__name__)


class AuditAgent:
    def __init__(self):
        self.persona = "You are the KAEOS Audit Agent. Expert in SOX compliance, internal controls testing, and financial audit management."

    async def get_control_status(self, db: AsyncSession, tenant_id: str) -> Dict[str, Any]:
        q = await db.execute(select(SOXControl).where(SOXControl.tenant_id == tenant_id))
        controls = q.scalars().all()

        effective = sum(1 for c in controls if c.status == SOXControlStatus.EFFECTIVE)
        needs_improvement = sum(1 for c in controls if c.status == SOXControlStatus.NEEDS_IMPROVEMENT)
        ineffective = sum(1 for c in controls if c.status == SOXControlStatus.INEFFECTIVE)
        not_assessed = sum(1 for c in controls if c.status == SOXControlStatus.NOT_ASSESSED)

        return {
            "total_controls": len(controls),
            "effective": effective,
            "needs_improvement": needs_improvement,
            "ineffective": ineffective,
            "not_assessed": not_assessed,
            "effectiveness_rate": round(effective / max(len(controls), 1) * 100, 1),
            "overdue_tests": [
                {"id": c.id, "code": c.control_id_code, "name": c.name, "area": c.area, "next_test": str(c.next_test_date)}
                for c in controls if c.next_test_date and c.next_test_date < __import__('datetime').date.today()
            ]
        }

    async def get_open_findings(self, db: AsyncSession, tenant_id: str) -> List[Dict[str, Any]]:
        q = await db.execute(
            select(AuditFinding).where(AuditFinding.tenant_id == tenant_id).where(AuditFinding.status.in_([FindingStatus.OPEN, FindingStatus.IN_PROGRESS]))
        )
        findings = q.scalars().all()
        return [
            {"id": f.id, "number": f.finding_number, "title": f.title, "severity": f.severity.value,
             "status": f.status.value, "area": f.area, "financial_impact": float(f.financial_impact or 0),
             "owner": f.remediation_owner, "target_date": str(f.target_remediation_date) if f.target_remediation_date else None,
             "ai_detected": f.ai_detected}
            for f in findings
        ]
