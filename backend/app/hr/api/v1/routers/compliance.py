"""KAEOS HR V1 — compliance

HR compliance: reports (including the real EEOC four-fifths self-audit)
and violation resolution.
"""
from datetime import datetime, timezone
from typing import Dict, Any, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import record_security_event
from app.core.database import get_db
from app.core.department_endpoints import get_or_404
from app.core.tenant import approver_identity, get_tenant_id, require_role
from app.hr.models.compliance import ComplianceReport, ComplianceViolation

router = APIRouter()


# ── Compliance & Reporting ─────────────────────────────────────────────────────

class ComplianceReportCreate(BaseModel):
    framework: str = Field(..., pattern="^(EEOC|OSHA|HIPAA|I9|GDPR|ACA)$")
    report_name: str
    period_year: int = Field(..., ge=2020, le=2100)
    data: Dict[str, Any] = Field(default_factory=dict)


@router.get("/compliance-reports")
async def list_compliance_reports(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(
        select(ComplianceReport).where(ComplianceReport.tenant_id == tenant_id)
        .order_by(ComplianceReport.generated_at.desc()).limit(200)
    )).scalars().all()
    return [{
        "id": r.id, "framework": r.framework.value if hasattr(r.framework, "value") else str(r.framework),
        "report_name": r.report_name, "period_year": r.period_year, "status": r.status, "data": r.data or {},
        "generated_at": r.generated_at.isoformat() if r.generated_at else None,
        "submitted_at": r.submitted_at.isoformat() if r.submitted_at else None,
    } for r in rows]


@router.post("/compliance-reports", status_code=201)
async def create_compliance_report(
    body: ComplianceReportCreate, tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db),
):
    tenant_id = tenant["tenant_id"]
    report = ComplianceReport(
        tenant_id=tenant_id, framework=body.framework, report_name=body.report_name,
        period_year=body.period_year, data=body.data,
    )
    db.add(report)
    await db.commit()
    await db.refresh(report)
    await record_security_event(tenant_id=tenant_id, event_type="MODIFICATION", action="WRITE",
        actor=approver_identity(tenant), actor_role=tenant.get("role"),
        resource_type="compliance_report", resource_id=report.id)
    return {"id": report.id, "framework": report.framework.value}


@router.post("/compliance-reports/eeoc/generate", status_code=201)
async def generate_eeoc_compliance_report(
    tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db),
):
    """Run the real EEOC four-fifths disparate-impact test across every
    requisition's candidates tenant-wide and persist it as a ComplianceReport
    (plus a BLOCKER ComplianceViolation on any adverse-impact finding).
    Reuses the exact statistical test the per-requisition fairness sweep
    runs — never a fabricated compliance score."""
    tenant_id = tenant["tenant_id"]
    from app.hr.services.fairness_sweep import build_cohort_outcomes
    from app.services.disparate_impact import four_fifths_test

    built = await build_cohort_outcomes(db, tenant_id, requisition_id=None)
    test_result = four_fifths_test(built["cohorts"])
    year = datetime.now(timezone.utc).year
    report = ComplianceReport(
        tenant_id=tenant_id, framework="EEOC",
        report_name=f"EEO adverse-impact self-audit {year}", period_year=year,
        data={"decided_total": built["decided_total"], **test_result}, status="GENERATED",
    )
    db.add(report)
    if not test_result["passed"]:
        db.add(ComplianceViolation(
            tenant_id=tenant_id, framework="EEOC", severity="BLOCKER",
            description=f"Adverse impact detected on {', '.join(test_result['flagged'])} across the candidate "
                        "pool (four-fifths rule, statistically significant).",
            context=test_result, actor_id="hr_compliance_report_generator",
        ))
    await db.commit()
    await db.refresh(report)
    await record_security_event(tenant_id=tenant_id, event_type="MODIFICATION", action="EXECUTE",
        actor=approver_identity(tenant), actor_role=tenant.get("role"),
        resource_type="compliance_report", resource_id=report.id, details={"passed": test_result["passed"]})
    return {"id": report.id, "passed": test_result["passed"], "flagged": test_result["flagged"],
            "decided_total": built["decided_total"]}


class ViolationResolve(BaseModel):
    resolution_notes: str = Field(..., max_length=512)


@router.get("/compliance-violations")
async def list_compliance_violations(
    resolved: Optional[bool] = None,
    tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db),
):
    stmt = select(ComplianceViolation).where(ComplianceViolation.tenant_id == tenant_id)
    if resolved is not None:
        stmt = stmt.where(ComplianceViolation.resolved == resolved)
    rows = (await db.execute(stmt.order_by(ComplianceViolation.created_at.desc()).limit(200))).scalars().all()
    return [{
        "id": v.id, "framework": v.framework, "severity": v.severity, "description": v.description,
        "resolved": v.resolved, "resolution_notes": v.resolution_notes,
        "created_at": v.created_at.isoformat() if v.created_at else None,
    } for v in rows]


@router.post("/compliance-violations/{violation_id}/resolve")
async def resolve_compliance_violation(
    violation_id: str, body: ViolationResolve,
    tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db),
):
    tenant_id = tenant["tenant_id"]
    v = await get_or_404(db, ComplianceViolation, violation_id, tenant_id, detail="Violation not found")
    v.resolved = True
    v.resolution_notes = body.resolution_notes
    db.add(v)
    await db.commit()
    await record_security_event(tenant_id=tenant_id, event_type="MODIFICATION", action="WRITE",
        actor=approver_identity(tenant), actor_role=tenant.get("role"),
        resource_type="compliance_violation", resource_id=violation_id)
    return {"id": violation_id, "resolved": True}
