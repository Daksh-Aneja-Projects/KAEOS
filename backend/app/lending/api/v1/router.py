"""
KAEOS Lending Domain - V1 API Router (prefix=/lending)

Loan-application CRUD, gated underwriting, adverse-action issuance, and the
dashboard. Reads use get_tenant_id; writes require the operator role. The
approver/decider is derived from the authenticated principal, never client input.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func as sqlfunc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.tenant import approver_identity, get_tenant_id, require_role
from app.lending.agents.adverse_action_agent import AdverseActionAgent
from app.lending.agents.underwriter_agent import UnderwriterAgent
from app.lending.models.core import (AdverseActionNotice, LoanApplication,
                                     LoanStatus, UnderwritingDecision)
from app.lending.services.analytics import lending_analytics
from app.lending.services.underwriting import LendingError, UnderwritingGateError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/lending", tags=["Lending"])

# Protected-class attributes are access-controlled: only admins see them on reads.
_ADMIN_ROLES = {"admin"}


class ApplicationIn(BaseModel):
    application_number: str
    applicant_name: str
    amount: float
    product: str = "personal_loan"
    credit_purpose: str = "consumer"
    term_months: Optional[int] = None
    credit_score: Optional[int] = None
    annual_income: Optional[float] = None
    monthly_debt: Optional[float] = None
    dti_ratio: Optional[float] = None
    protected_class: Optional[dict] = None
    applicant_ref: Optional[str] = None


class UnderwriteIn(BaseModel):
    approval_cohorts: Optional[dict] = None
    business_necessity: Optional[str] = None


def _app_out(a: LoanApplication, *, include_protected: bool) -> dict:
    out = {
        "id": a.id, "application_number": a.application_number,
        "applicant_name": a.applicant_name, "product": a.product,
        "credit_purpose": a.credit_purpose, "amount": float(a.amount or 0),
        "term_months": a.term_months, "credit_score": a.credit_score,
        "annual_income": float(a.annual_income) if a.annual_income is not None else None,
        "dti_ratio": float(a.dti_ratio) if a.dti_ratio is not None else None,
        "status": a.status,
        "intake_score": float(a.intake_score) if a.intake_score is not None else None,
    }
    if include_protected:
        out["protected_class"] = a.protected_class or {}
    return out


@router.get("/dashboard")
async def lending_dashboard(tenant_id: str = Depends(get_tenant_id),
                            db: AsyncSession = Depends(get_db)):
    return await lending_analytics(db, tenant_id, charts=True)


@router.get("/applications")
async def list_applications(tenant: dict = Depends(require_role("viewer")),
                            status: Optional[str] = None,
                            db: AsyncSession = Depends(get_db)):
    tenant_id = tenant["tenant_id"]
    q = select(LoanApplication).where(LoanApplication.tenant_id == tenant_id)
    if status:
        q = q.where(LoanApplication.status == status)
    rows = (await db.execute(q.order_by(LoanApplication.created_at.desc()).limit(200))).scalars().all()
    include = tenant.get("role") in _ADMIN_ROLES
    return [_app_out(a, include_protected=include) for a in rows]


@router.get("/applications/{application_id}")
async def get_application(application_id: str,
                          tenant: dict = Depends(require_role("viewer")),
                          db: AsyncSession = Depends(get_db)):
    tenant_id = tenant["tenant_id"]
    a = (await db.execute(select(LoanApplication).where(
        LoanApplication.id == application_id,
        LoanApplication.tenant_id == tenant_id))).scalar_one_or_none()
    if not a:
        raise HTTPException(status_code=404, detail="Application not found")
    return _app_out(a, include_protected=tenant.get("role") in _ADMIN_ROLES)


@router.post("/applications")
async def create_application(body: ApplicationIn,
                             tenant: dict = Depends(require_role("operator")),
                             db: AsyncSession = Depends(get_db)):
    tenant_id = tenant["tenant_id"]
    app = LoanApplication(
        tenant_id=tenant_id, application_number=body.application_number,
        applicant_name=body.applicant_name, applicant_ref=body.applicant_ref,
        product=body.product, credit_purpose=body.credit_purpose,
        amount=body.amount, term_months=body.term_months,
        credit_score=body.credit_score, annual_income=body.annual_income,
        monthly_debt=body.monthly_debt, dti_ratio=body.dti_ratio,
        protected_class=body.protected_class or {},
        status=LoanStatus.RECEIVED.value,
    )
    db.add(app)
    await db.commit()
    await db.refresh(app)
    return _app_out(app, include_protected=True)


@router.post("/applications/{application_id}/underwrite")
async def underwrite(application_id: str, body: UnderwriteIn = UnderwriteIn(),
                     tenant: dict = Depends(require_role("operator")),
                     db: AsyncSession = Depends(get_db)):
    try:
        return await UnderwriterAgent().underwrite(
            db, application_id, tenant["tenant_id"],
            decided_by=approver_identity(tenant),
            approval_cohorts=body.approval_cohorts,
            business_necessity=body.business_necessity)
    except UnderwritingGateError as e:
        # Fail-closed decision surfaced as 422 with the blocking findings.
        raise HTTPException(status_code=422, detail={"error": str(e), "blocking": e.blocking})
    except LendingError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/applications/{application_id}/adverse-action")
async def issue_adverse_action(application_id: str,
                               tenant: dict = Depends(require_role("operator")),
                               db: AsyncSession = Depends(get_db)):
    try:
        return await AdverseActionAgent().issue(
            db, application_id, tenant["tenant_id"],
            issued_by=approver_identity(tenant))
    except UnderwritingGateError as e:
        raise HTTPException(status_code=422, detail={"error": str(e), "blocking": e.blocking})
    except LendingError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/adverse-action")
async def list_adverse_actions(tenant_id: str = Depends(get_tenant_id),
                               db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(AdverseActionNotice).where(
        AdverseActionNotice.tenant_id == tenant_id)
        .order_by(AdverseActionNotice.created_at.desc()).limit(200))).scalars().all()
    return [{"id": n.id, "application_id": n.application_id,
             "specific_reasons": n.specific_reasons,
             "decision_date": n.decision_date.isoformat() if n.decision_date else None,
             "sent_at": n.sent_at.isoformat() if n.sent_at else None,
             "within_30_days": n.within_30_days} for n in rows]
