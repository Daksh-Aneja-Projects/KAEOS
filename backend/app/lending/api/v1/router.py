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

from app.core.audit import record_security_event
from app.core.database import get_db
from app.core.tenant import approver_identity, get_tenant_id, require_role
from app.lending.agents.adverse_action_agent import AdverseActionAgent
from app.lending.agents.collections_agent import CollectionsAgent
from app.lending.agents.intake_agent import IntakeAgent
from app.lending.agents.underwriter_agent import UnderwriterAgent
from app.lending.models.core import (AdverseActionNotice, CreditPolicy,
                                     LoanApplication, LoanStatus,
                                     UnderwritingDecision)
from app.lending.models.servicing import CollectionCase, ServicedLoan
from app.lending.services.analytics import lending_analytics
from app.lending.services.servicing import (CaseNotFound, CollectionGateError,
                                            attempt_collection_contact,
                                            delinquency_bucket)
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


class CreditPolicyIn(BaseModel):
    min_credit_score: int
    max_dti_ratio: float
    min_annual_income: float
    max_amount: float
    base_apr: float
    is_active: bool = True


class CollectionContactIn(BaseModel):
    hour_local: int
    channel: str = "phone"
    harassment: bool = False
    notes: Optional[str] = None


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


@router.get("/analytics")
async def get_lending_analytics(tenant_id: str = Depends(get_tenant_id),
                                db: AsyncSession = Depends(get_db)):
    """Same payload as /dashboard, on the path every other department uses.

    The shared DomainAnalytics component fetches /{domain}/analytics, so without
    this lending is the one department whose analytics tab cannot render.
    """
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

    # Governed intake: every application is validated and scored automatically
    # on receipt (IntakeAgent.validate_and_score was fully built but never
    # called - every application sat un-triaged until a human ran underwriting).
    try:
        await IntakeAgent().validate_and_score(db, app.id, tenant_id)
        await db.refresh(app)
    except ValueError as e:
        logger.warning("Intake validation failed for application %s: %s", app.id, e)

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


# ═══════════════════════════════════════════════════════════════════════
# Credit Policy — drives every automated underwriting decision
# ═══════════════════════════════════════════════════════════════════════

def _policy_out(p: CreditPolicy) -> dict:
    return {
        "id": p.id, "product": p.product,
        "min_credit_score": p.min_credit_score,
        "max_dti_ratio": float(p.max_dti_ratio),
        "min_annual_income": float(p.min_annual_income),
        "max_amount": float(p.max_amount),
        "base_apr": float(p.base_apr),
        "is_active": bool(p.is_active),
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
    }


@router.get("/credit-policies")
async def list_credit_policies(tenant: dict = Depends(require_role("viewer")),
                               db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(CreditPolicy).where(
        CreditPolicy.tenant_id == tenant["tenant_id"]).order_by(CreditPolicy.product)
        )).scalars().all()
    return [_policy_out(p) for p in rows]


@router.put("/credit-policies/{product}")
async def put_credit_policy(product: str, body: CreditPolicyIn,
                            tenant: dict = Depends(require_role("admin")),
                            db: AsyncSession = Depends(get_db)):
    """Upsert the credit-policy thresholds for one product (admin only). These
    thresholds are the ONLY input to the deterministic underwriting decision -
    validated at the boundary so a bad edit cannot silently corrupt every
    future decision on this product."""
    if not (300 <= body.min_credit_score <= 850):
        raise HTTPException(400, detail="min_credit_score must be between 300 and 850")
    if not (0 < body.max_dti_ratio <= 2):
        raise HTTPException(400, detail="max_dti_ratio must be a positive ratio (e.g. 0.45)")
    if body.min_annual_income < 0:
        raise HTTPException(400, detail="min_annual_income must not be negative")
    if body.max_amount <= 0:
        raise HTTPException(400, detail="max_amount must be positive")
    if not (0 <= body.base_apr <= 100):
        raise HTTPException(400, detail="base_apr must be between 0 and 100")

    tenant_id = tenant["tenant_id"]
    row = (await db.execute(select(CreditPolicy).where(
        CreditPolicy.tenant_id == tenant_id, CreditPolicy.product == product)
        )).scalar_one_or_none()
    if row is None:
        row = CreditPolicy(tenant_id=tenant_id, product=product)
        db.add(row)

    row.min_credit_score = body.min_credit_score
    row.max_dti_ratio = body.max_dti_ratio
    row.min_annual_income = body.min_annual_income
    row.max_amount = body.max_amount
    row.base_apr = body.base_apr
    row.is_active = body.is_active

    await db.commit()
    await db.refresh(row)
    await record_security_event(
        tenant_id=tenant_id, event_type="CONFIG_CHANGE", action="WRITE",
        actor=approver_identity(tenant), actor_role=tenant.get("role"),
        resource_type="credit_policy", resource_id=row.id,
        details={"product": product},
    )
    return _policy_out(row)


# ═══════════════════════════════════════════════════════════════════════
# Loan Servicing + Collections (FDCPA-governed)
# ═══════════════════════════════════════════════════════════════════════

def _loan_out(loan: ServicedLoan) -> dict:
    return {
        "id": loan.id, "application_id": loan.application_id,
        "loan_number": loan.loan_number, "product": loan.product,
        "borrower_name": loan.borrower_name,
        "principal": float(loan.principal),
        "outstanding_principal": float(loan.outstanding_principal),
        "apr": float(loan.apr), "term_months": loan.term_months,
        "monthly_payment": float(loan.monthly_payment),
        "next_due_date": loan.next_due_date.isoformat() if loan.next_due_date else None,
        "last_payment_date": loan.last_payment_date.isoformat() if loan.last_payment_date else None,
        "last_payment_amount": float(loan.last_payment_amount) if loan.last_payment_amount is not None else None,
        "payments_made": loan.payments_made, "days_past_due": loan.days_past_due,
        "status": loan.status,
        "delinquency_bucket": delinquency_bucket(loan.days_past_due),
        "payment_schedule": loan.payment_schedule or [],
    }


@router.get("/serviced-loans")
async def list_serviced_loans(status: Optional[str] = None,
                              tenant: dict = Depends(require_role("viewer")),
                              db: AsyncSession = Depends(get_db)):
    q = select(ServicedLoan).where(ServicedLoan.tenant_id == tenant["tenant_id"])
    if status:
        q = q.where(ServicedLoan.status == status)
    rows = (await db.execute(q.order_by(ServicedLoan.next_due_date.asc()))).scalars().all()
    return [_loan_out(loan) for loan in rows]


@router.get("/delinquencies")
async def list_delinquencies(tenant: dict = Depends(require_role("viewer")),
                             db: AsyncSession = Depends(get_db)):
    """Every open collections case, bucketed by days-past-due, with its
    loan context and full contact log - the servicing team's working queue."""
    tenant_id = tenant["tenant_id"]
    cases = (await db.execute(select(CollectionCase).where(
        CollectionCase.tenant_id == tenant_id)
        .order_by(CollectionCase.opened_at.desc()))).scalars().all()

    loan_ids = list({c.serviced_loan_id for c in cases})
    loans_by_id = {}
    if loan_ids:
        loan_rows = (await db.execute(select(ServicedLoan).where(
            ServicedLoan.tenant_id == tenant_id,
            ServicedLoan.id.in_(loan_ids)))).scalars().all()
        loans_by_id = {loan.id: loan for loan in loan_rows}

    buckets: dict = {}
    cases_out = []
    for c in cases:
        loan = loans_by_id.get(c.serviced_loan_id)
        bucket = c.delinquency_bucket or "1-29"
        buckets[bucket] = buckets.get(bucket, 0) + 1
        cases_out.append({
            "id": c.id, "serviced_loan_id": c.serviced_loan_id,
            "loan_number": loan.loan_number if loan else None,
            "borrower_name": loan.borrower_name if loan else None,
            "outstanding_principal": float(loan.outstanding_principal) if loan else None,
            "days_past_due": loan.days_past_due if loan else None,
            "status": c.status, "delinquency_bucket": bucket,
            "validation_notice_sent": c.validation_notice_sent,
            "validation_notice_sent_at": c.validation_notice_sent_at.isoformat() if c.validation_notice_sent_at else None,
            "opened_at": c.opened_at.isoformat() if c.opened_at else None,
            "last_contact_at": c.last_contact_at.isoformat() if c.last_contact_at else None,
            "contact_log": c.contact_log or [],
        })

    return {
        "cases": cases_out,
        "buckets": [{"label": k, "value": v} for k, v in sorted(buckets.items())],
    }


@router.post("/collection-cases/{case_id}/contact")
async def attempt_collection_case_contact(
    case_id: str, body: CollectionContactIn,
    tenant: dict = Depends(require_role("operator")),
    db: AsyncSession = Depends(get_db),
):
    """Attempt a debt-collection contact, gated fail-closed by FDCPA (contact
    hour window, harassment flag, validation-notice timing). A blocking
    verdict is surfaced as 422; nothing is persisted on a block."""
    try:
        return await CollectionsAgent().contact(
            db, case_id, tenant["tenant_id"],
            hour_local=body.hour_local, channel=body.channel,
            harassment=body.harassment, notes=body.notes,
            actor=approver_identity(tenant))
    except CollectionGateError as e:
        raise HTTPException(status_code=422, detail={"error": str(e), "blocking": e.blocking})
    except CaseNotFound as e:
        raise HTTPException(status_code=404, detail=str(e))
    except LendingError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ═══════════════════════════════════════════════════════════════════════
# Analytics & Workflow Layer (shared engine: app.core.workflow)
# ═══════════════════════════════════════════════════════════════════════
from app.core.workflow import (  # noqa: E402
    TransitionRequest, apply_transition, list_workflow_events,
)
from app.lending.services.workflows import SPECS as WORKFLOW_SPECS  # noqa: E402


@router.get("/workflows")
async def get_lending_workflows(tenant_id: str = Depends(get_tenant_id)):
    """Declared state machines - the frontend renders transition actions from this."""
    return {name: spec.describe() for name, spec in WORKFLOW_SPECS.items()}


@router.get("/workflow-events")
async def get_lending_workflow_events(
    entity_type: Optional[str] = None, entity_id: Optional[str] = None,
    tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db),
):
    """Tenant-scoped transition audit trail for lending entities."""
    return await list_workflow_events(db, tenant_id, domain="lending",
                                      entity_type=entity_type, entity_id=entity_id)


@router.post("/applications/{application_id}/transition")
async def transition_application(
    application_id: str, body: TransitionRequest,
    tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db),
):
    """Guarded application lifecycle action. Only WITHDRAWN is reachable here -
    APPROVED/DENIED/PENDING_HITL only ever come from the gated /underwrite
    decision, never a bare status write."""
    return await apply_transition(db, WORKFLOW_SPECS["loan_application"],
                                  application_id, body.to_state, tenant, note=body.note)


@router.post("/serviced-loans/{loan_id}/transition")
async def transition_serviced_loan(
    loan_id: str, body: TransitionRequest,
    tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db),
):
    """Guarded serviced-loan delinquency lifecycle action (cure, escalate to
    default, pay off)."""
    return await apply_transition(db, WORKFLOW_SPECS["serviced_loan"],
                                  loan_id, body.to_state, tenant, note=body.note)
