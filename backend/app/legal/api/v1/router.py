"""
KAEOS Legal Domain — V1 API Router
CRUD and agent workflow triggers.
"""
from app.core.tenant import get_tenant_id, require_role
from app.core.audit import record_security_event
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func as sqlfunc

from app.core.database import get_db

# Models
from app.legal.models.core import LegalMatter, LegalTeamMember, MatterPriority
from app.legal.models.contracts import Contract, ContractClause, ContractTemplate
from app.legal.models.compliance import (
    ComplianceAssessment, ComplianceObligation, RegulatoryRequirement,
)
from app.legal.models.litigation import Case, CaseEvent, CaseStage, CourtFiling
from app.legal.models.ip import Patent, Trademark, TradeSecret
from app.legal.models.privacy import DataProcessingRecord, DataSubjectRequest, DsarStatus, PrivacyImpactAssessment

# Agents
from app.legal.agents.contract_review_agent import ContractReviewAgent
from app.legal.agents.compliance_audit_agent import ComplianceAuditAgent
from app.legal.agents.litigation_agent import LitigationAgent
from app.legal.agents.privacy_dsar_agent import PrivacyDSARAgent
from app.legal.agents.ip_agent import IPAgent
from app.legal.services.compliance_gates import ConflictOfInterestBlocked, screen_new_matter

import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/legal", tags=["Legal"])

# --- Dashboard ---
@router.get("/dashboard")
async def legal_dashboard(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    # Matters
    matter_q = await db.execute(select(sqlfunc.count()).select_from(LegalMatter).where(LegalMatter.tenant_id == tenant_id))
    total_matters = matter_q.scalar() or 0

    # Active Contracts
    contract_q = await db.execute(
        select(sqlfunc.count()).select_from(Contract).where(Contract.tenant_id == tenant_id)
        .where(Contract.status == "ACTIVE")
    )
    active_contracts = contract_q.scalar() or 0

    # In-flight DSARs — every request not yet terminal (COMPLETED/FAILED), so
    # ones being verified or processed still count against their statutory
    # deadline instead of dropping off the moment they leave RECEIVED. Matches
    # the terminal set legal_analytics uses.
    dsar_q = await db.execute(
        select(sqlfunc.count()).select_from(DataSubjectRequest).where(DataSubjectRequest.tenant_id == tenant_id)
        .where(DataSubjectRequest.status.notin_([DsarStatus.COMPLETED, DsarStatus.FAILED]))
    )
    pending_dsars = dsar_q.scalar() or 0

    # Active Cases
    case_q = await db.execute(
        select(sqlfunc.count()).select_from(Case).where(Case.tenant_id == tenant_id)
        .where(Case.stage.in_([CaseStage.PLEADING, CaseStage.DISCOVERY, CaseStage.MOTION, CaseStage.TRIAL]))
    )
    active_cases = case_q.scalar() or 0

    return {
        "total_matters": total_matters,
        "active_contracts": active_contracts,
        "pending_dsars": pending_dsars,
        "active_lawsuits": active_cases,
    }

# --- General Matters ---
@router.get("/matters")
async def list_matters(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    # Resolve the attorney id to a human-readable name — never surface a raw id.
    q = await db.execute(
        select(LegalMatter, LegalTeamMember.name)
        .outerjoin(LegalTeamMember, LegalMatter.assigned_attorney_id == LegalTeamMember.id)
        .where(LegalMatter.tenant_id == tenant_id)
        .limit(200)
    )
    rows = q.all()
    return [{
        "id": m.id, "title": m.title, "description": m.description, "type": m.matter_type,
        "status": m.status.value, "priority": m.priority.value, "exposure": m.estimated_exposure,
        "assigned_attorney": attorney_name, "external_counsel": m.external_counsel,
        "resolution": m.resolution,
    } for m, attorney_name in rows]

# --- Contracts ---
@router.get("/contracts")
async def list_contracts(
    tenant_id: str = Depends(get_tenant_id),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    q = await db.execute(select(Contract).where(Contract.tenant_id == tenant_id).limit(limit).offset(offset))
    contracts = q.scalars().all()
    return [{"id": c.id, "title": c.title, "counterparty": c.counterparty, "status": c.status.value, "value": float(c.contract_value or 0), "risk_score": float(c.ai_risk_score or 0), "expiry": str(c.expiry_date) if c.expiry_date else None} for c in contracts]

@router.get("/contracts/{contract_id}/clauses")
async def get_clauses(contract_id: str, tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    # IDOR: returned the full legal text of ANY contract to ANY caller.
    q = await db.execute(
        select(ContractClause)
        .where(ContractClause.tenant_id == tenant_id, ContractClause.contract_id == contract_id)
        .limit(200)
    )
    clauses = q.scalars().all()
    return [{"id": c.id, "type": c.clause_type, "text": c.original_text, "risk": c.risk_level.value, "analysis": c.ai_analysis} for c in clauses]

@router.get("/contract-templates")
async def list_contract_templates(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    q = await db.execute(select(ContractTemplate).where(ContractTemplate.tenant_id == tenant_id).limit(200))
    templates = q.scalars().all()
    return [{"id": t.id, "name": t.name, "contract_type": t.contract_type, "version": t.version, "is_active": t.is_active} for t in templates]

@router.post("/contracts/{contract_id}/review")
async def review_contract(contract_id: str, tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db)):
    """Full 7-gate review (compliance -> fairness -> HITL -> debate -> execute -> audit)."""
    tenant_id = tenant["tenant_id"]
    agent = ContractReviewAgent()
    try:
        result = await agent.review_contract(db, contract_id, tenant_id)
        await record_security_event(
            tenant_id=tenant_id, event_type="MODIFICATION", action="EXECUTE",
            actor=tenant.get("name"), actor_role=tenant.get("role"),
            resource_type="contract", resource_id=contract_id,
        )
        return result
    except ValueError as e:
        raise HTTPException(404, detail=str(e))
    except Exception as e:
        logger.exception("%s failed", __name__)
        raise HTTPException(500, detail="Internal error - see server logs") from e

# --- Compliance ---
@router.get("/compliance/obligations")
async def list_obligations(
    tenant_id: str = Depends(get_tenant_id),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    q = await db.execute(select(ComplianceObligation).where(ComplianceObligation.tenant_id == tenant_id).limit(limit).offset(offset))
    obs = q.scalars().all()
    return [{"id": o.id, "title": o.title, "description": o.description, "status": o.status.value, "owner": o.owner, "due_date": str(o.due_date) if o.due_date else None} for o in obs]

@router.get("/compliance/requirements")
async def list_regulatory_requirements(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    q = await db.execute(select(RegulatoryRequirement).where(RegulatoryRequirement.tenant_id == tenant_id).limit(200))
    reqs = q.scalars().all()
    return [{"id": r.id, "regulation": r.regulation, "section": r.section, "title": r.title,
             "description": r.description, "jurisdiction": r.jurisdiction} for r in reqs]

@router.get("/compliance/assessments")
async def list_compliance_assessments(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    q = await db.execute(select(ComplianceAssessment).where(ComplianceAssessment.tenant_id == tenant_id).limit(200))
    assessments = q.scalars().all()
    return [{"id": a.id, "framework": a.framework, "assessment_date": str(a.assessment_date),
             "assessor": a.assessor, "score": float(a.score) if a.score is not None else None,
             "findings_count": a.findings_count} for a in assessments]

@router.post("/compliance/obligations/{obligation_id}/audit")
async def audit_obligation(obligation_id: str, tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db)):
    tenant_id = tenant["tenant_id"]
    agent = ComplianceAuditAgent()
    try:
        result = await agent.audit_obligation(db, obligation_id, tenant_id)
        await record_security_event(
            tenant_id=tenant_id, event_type="MODIFICATION", action="EXECUTE",
            actor=tenant.get("name"), actor_role=tenant.get("role"),
            resource_type="obligation", resource_id=obligation_id,
        )
        return result
    except ValueError as e:
        raise HTTPException(404, detail=str(e))
    except Exception as e:
        logger.exception("%s failed", __name__)
        raise HTTPException(500, detail="Internal error - see server logs") from e

# --- Litigation ---
@router.get("/cases")
async def list_cases(
    tenant_id: str = Depends(get_tenant_id),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    q = await db.execute(select(Case).where(Case.tenant_id == tenant_id).limit(limit).offset(offset))
    cases = q.scalars().all()
    return [{"id": c.id, "name": c.case_name, "stage": c.stage.value, "exposure": float(c.exposure_amount or 0), "opposing_party": c.opposing_party, "court": c.court} for c in cases]

@router.get("/cases/{case_id}/events")
async def list_case_events(case_id: str, tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    """Litigation timeline: hearings, deposition dates, discovery requests."""
    q = await db.execute(
        select(CaseEvent)
        .where(CaseEvent.tenant_id == tenant_id, CaseEvent.case_id == case_id)
        .order_by(CaseEvent.event_date)
        .limit(200)
    )
    events = q.scalars().all()
    return [{"id": e.id, "title": e.event_title, "date": str(e.event_date), "description": e.description,
             "is_milestone": e.is_milestone == "Yes"} for e in events]

@router.get("/cases/{case_id}/filings")
async def list_case_filings(case_id: str, tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    """Court submissions, summons and briefs filed for this case."""
    q = await db.execute(
        select(CourtFiling)
        .where(CourtFiling.tenant_id == tenant_id, CourtFiling.case_id == case_id)
        .order_by(CourtFiling.filing_date.desc())
        .limit(200)
    )
    filings = q.scalars().all()
    return [{"id": f.id, "document_name": f.document_name, "filing_date": str(f.filing_date),
             "filed_by": f.filed_by} for f in filings]

@router.post("/cases/{case_id}/evaluate")
async def evaluate_case(case_id: str, tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db)):
    # The old body fell back to `agent.evaluate_exposure`, which does not
    # exist - so ANY failure in evaluate_case surfaced as
    # "'LitigationAgent' object has no attribute 'evaluate_exposure'",
    # hiding the real cause behind a dead compatibility branch.
    tenant_id = tenant["tenant_id"]
    agent = LitigationAgent()
    try:
        result = await agent.evaluate_case(db, case_id, tenant_id)
        await record_security_event(
            tenant_id=tenant_id, event_type="MODIFICATION", action="EXECUTE",
            actor=tenant.get("name"), actor_role=tenant.get("role"),
            resource_type="case", resource_id=case_id,
        )
        return result
    except ValueError as e:
        raise HTTPException(404, detail=str(e))
    except Exception as e:
        logger.exception("legal case evaluation failed")
        raise HTTPException(500, detail="Internal error - see server logs") from e

# --- Privacy ---
@router.get("/privacy/dsars")
async def list_dsars(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    q = await db.execute(select(DataSubjectRequest).where(DataSubjectRequest.tenant_id == tenant_id).limit(200))
    dsars = q.scalars().all()
    return [{"id": d.id, "name": d.requestor_name, "email": d.requestor_email, "type": d.request_type.value, "status": d.status.value, "deadline": str(d.deadline_date)} for d in dsars]

@router.get("/privacy/pias")
async def list_pias(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    q = await db.execute(select(PrivacyImpactAssessment).where(PrivacyImpactAssessment.tenant_id == tenant_id).limit(200))
    pias = q.scalars().all()
    return [{"id": p.id, "system_name": p.system_name, "pii_elements": p.pii_elements,
             "risk_rating": p.risk_rating, "remediation_required": p.remediation_required,
             "status": p.status, "signoff_date": str(p.signoff_date) if p.signoff_date else None} for p in pias]

@router.get("/privacy/ropa")
async def list_ropa(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    """Records of Processing Activities (GDPR Art 30)."""
    q = await db.execute(select(DataProcessingRecord).where(DataProcessingRecord.tenant_id == tenant_id).limit(200))
    records = q.scalars().all()
    return [{"id": r.id, "data_controller": r.data_controller, "purpose": r.purpose_of_processing,
             "subjects": r.categories_of_subjects, "recipients": r.categories_of_recipients,
             "retention_period": r.retention_period} for r in records]

@router.post("/privacy/dsars/{dsar_id}/validate")
async def validate_dsar(dsar_id: str, tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db)):
    tenant_id = tenant["tenant_id"]
    agent = PrivacyDSARAgent()
    try:
        result = await agent.process_dsar(db, dsar_id, tenant_id)
        await record_security_event(
            tenant_id=tenant_id, event_type="MODIFICATION", action="EXECUTE",
            actor=tenant.get("name"), actor_role=tenant.get("role"),
            resource_type="dsar", resource_id=dsar_id,
        )
        return result
    except ValueError as e:
        raise HTTPException(404, detail=str(e))
    except Exception as e:
        logger.exception("%s failed", __name__)
        raise HTTPException(500, detail="Internal error - see server logs") from e

# --- IP ---
@router.get("/ip/patents")
async def list_patents(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    q = await db.execute(select(Patent).where(Patent.tenant_id == tenant_id).limit(200))
    patents = q.scalars().all()
    return [{"id": p.id, "title": p.title, "number": p.patent_number, "status": p.status.value, "filing_date": str(p.filing_date) if p.filing_date else None, "jurisdiction": p.jurisdiction} for p in patents]

@router.get("/ip/trademarks")
async def list_trademarks(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    q = await db.execute(select(Trademark).where(Trademark.tenant_id == tenant_id).limit(200))
    marks = q.scalars().all()
    return [{"id": t.id, "mark_name": t.mark_name, "registration_number": t.registration_number,
             "status": t.status.value, "class_code": t.class_code, "jurisdiction": t.jurisdiction,
             "renewal_date": str(t.renewal_date) if t.renewal_date else None} for t in marks]

@router.get("/ip/trade-secrets")
async def list_trade_secrets(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    q = await db.execute(select(TradeSecret).where(TradeSecret.tenant_id == tenant_id).limit(200))
    secrets = q.scalars().all()
    return [{"id": s.id, "asset_name": s.asset_name, "description": s.description,
             "custodian": s.custodian, "security_level": s.security_level} for s in secrets]

@router.post("/ip/patents/{patent_id}/evaluate")
async def evaluate_patent(patent_id: str, tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db)):
    tenant_id = tenant["tenant_id"]
    agent = IPAgent()
    try:
        result = await agent.evaluate_patentability(db, patent_id, tenant_id)
        await record_security_event(
            tenant_id=tenant_id, event_type="MODIFICATION", action="EXECUTE",
            actor=tenant.get("name"), actor_role=tenant.get("role"),
            resource_type="patent", resource_id=patent_id,
        )
        return result
    except ValueError as e:
        # 404 (not 403) so another tenant's id is not confirmed to exist.
        raise HTTPException(404, detail=str(e))
    except Exception as e:
        logger.exception("%s failed", __name__)
        raise HTTPException(500, detail="Internal error - see server logs") from e

# --- Team ---
@router.get("/team")
async def list_team(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    q = await db.execute(select(LegalTeamMember).where(LegalTeamMember.tenant_id == tenant_id).limit(200))
    team = q.scalars().all()
    return [{"id": m.id, "name": m.name, "role": m.role, "email": m.email,
             "bar_license_number": m.bar_license_number, "is_active": m.is_active} for m in team]

# ═══════════════════════════════════════════════════════════════════════
# Analytics & Workflow Layer (shared engine: app.core.workflow)
# ═══════════════════════════════════════════════════════════════════════
from typing import Optional  # noqa: E402
from app.core.workflow import (  # noqa: E402
    BulkTransitionRequest, TransitionRequest, apply_bulk_transition,
    apply_transition, list_workflow_events,
)
from app.legal.services.analytics import legal_analytics  # noqa: E402
from app.legal.services.workflows import SPECS as WORKFLOW_SPECS  # noqa: E402


@router.get("/analytics")
async def get_legal_analytics(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    """Computed contract portfolio, renewal and risk KPIs for the legal cockpit."""
    return await legal_analytics(db, tenant_id)


@router.get("/workflows")
async def get_legal_workflows(tenant_id: str = Depends(get_tenant_id)):
    """Declared state machines - the frontend renders contract actions from this."""
    return {name: spec.describe() for name, spec in WORKFLOW_SPECS.items()}


@router.get("/workflow-events")
async def get_legal_workflow_events(
    entity_type: Optional[str] = None, entity_id: Optional[str] = None,
    tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db),
):
    """Tenant-scoped transition audit trail for legal entities."""
    return await list_workflow_events(db, tenant_id, domain="legal",
                                      entity_type=entity_type, entity_id=entity_id)


@router.post("/contracts/{contract_id}/transition")
async def transition_contract(
    contract_id: str, body: TransitionRequest,
    tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db),
):
    """Move a contract through draft, review, approved, signed, active."""
    return await apply_transition(db, WORKFLOW_SPECS["contract"], contract_id,
                                  body.to_state, tenant, note=body.note)


@router.post("/matters/{matter_id}/transition")
async def transition_matter(
    matter_id: str, body: TransitionRequest,
    tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db),
):
    """Move a matter through new, in progress, on hold, resolved, closed.
    Closing is screened by the LEGAL_HOLD / RETENTION_SCHEDULE guard."""
    return await apply_transition(db, WORKFLOW_SPECS["matter"], matter_id,
                                  body.to_state, tenant, note=body.note)


@router.post("/compliance/obligations/{obligation_id}/transition")
async def transition_obligation(
    obligation_id: str, body: TransitionRequest,
    tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db),
):
    """Move a compliance obligation through pending, overdue, completed, waived."""
    return await apply_transition(db, WORKFLOW_SPECS["obligation"], obligation_id,
                                  body.to_state, tenant, note=body.note)

# ═══════════════════════════════════════════════════════════════════════
# Entity Creation
# ═══════════════════════════════════════════════════════════════════════
from datetime import date as _date  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402


class ContractCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=256)
    counterparty: str = Field(..., min_length=1, max_length=256)
    contract_type: str = Field(..., min_length=1, max_length=64)
    contract_value: Optional[float] = Field(None, ge=0)
    expiry_date: Optional[_date] = None
    auto_renew: bool = False


@router.post("/contracts", status_code=201)
async def create_contract(
    body: ContractCreate,
    tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db),
):
    """Register a contract (starts DRAFT; lifecycle via /transition)."""
    tenant_id = tenant["tenant_id"]
    c = Contract(
        tenant_id=tenant_id, title=body.title, counterparty=body.counterparty,
        contract_type=body.contract_type, contract_value=body.contract_value,
        expiry_date=body.expiry_date, auto_renew=body.auto_renew,
    )
    db.add(c)
    await db.commit()
    await db.refresh(c)
    await record_security_event(
        tenant_id=tenant_id, event_type="MODIFICATION", action="WRITE",
        actor=tenant.get("name"), actor_role=tenant.get("role"),
        resource_type="contract", resource_id=c.id,
    )
    return {"id": c.id, "title": c.title,
            "status": c.status.value if hasattr(c.status, "value") else str(c.status),
            "counterparty": c.counterparty, "contract_type": c.contract_type}


class MatterCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=256)
    description: Optional[str] = None
    matter_type: str = Field(..., min_length=1, max_length=64)
    priority: Optional[str] = Field(None, max_length=16)
    assigned_attorney_id: Optional[str] = None
    external_counsel: Optional[str] = Field(None, max_length=256)
    estimated_exposure: Optional[str] = None
    # Comma-separated party names — screened against adverse_parties by the
    # CONFLICT_OF_INTEREST checker (ABA Model Rule 1.7) before the matter is
    # opened. Either/both may be omitted; an unscreenable matter is
    # NOT_APPLICABLE, never a fabricated pass.
    parties: Optional[str] = Field(None, max_length=1024)
    adverse_parties: Optional[str] = Field(None, max_length=1024)


def _split_csv(raw: Optional[str]) -> Optional[list]:
    if not raw:
        return None
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    return parts or None


@router.post("/matters", status_code=201)
async def create_matter(
    body: MatterCreate,
    tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db),
):
    """Open a new legal matter. Screened by CONFLICT_OF_INTEREST
    (app/compliance/checkers/legal.py) before the row is persisted."""
    tenant_id = tenant["tenant_id"]
    parties = _split_csv(body.parties)
    adverse_parties = _split_csv(body.adverse_parties)
    try:
        screen_new_matter(parties, adverse_parties)
    except ConflictOfInterestBlocked as e:
        raise HTTPException(409, detail=str(e))

    try:
        priority = MatterPriority(body.priority.upper()) if body.priority else MatterPriority.MEDIUM
    except ValueError:
        raise HTTPException(422, detail=(
            f"Invalid priority '{body.priority}'. Expected one of "
            f"{[p.value for p in MatterPriority]}."
        ))

    attorney_id = body.assigned_attorney_id or None
    if attorney_id:
        # Tenant-scoped existence check — never let a cross-tenant id attach.
        found = (await db.execute(
            select(LegalTeamMember.id).where(
                LegalTeamMember.id == attorney_id, LegalTeamMember.tenant_id == tenant_id,
            )
        )).scalar_one_or_none()
        if not found:
            raise HTTPException(404, detail=f"Attorney {attorney_id} not found")

    m = LegalMatter(
        tenant_id=tenant_id, title=body.title, description=body.description,
        matter_type=body.matter_type, priority=priority,
        assigned_attorney_id=attorney_id,
        external_counsel=body.external_counsel, estimated_exposure=body.estimated_exposure,
    )
    db.add(m)
    await db.commit()
    await db.refresh(m)
    await record_security_event(
        tenant_id=tenant_id, event_type="MODIFICATION", action="WRITE",
        actor=tenant.get("name"), actor_role=tenant.get("role"),
        resource_type="matter", resource_id=m.id,
    )
    return {"id": m.id, "title": m.title, "type": m.matter_type,
            "status": m.status.value, "priority": m.priority.value}


@router.post("/workflows/{entity_type}/bulk-transition")
async def bulk_transition_legal(
    entity_type: str, body: BulkTransitionRequest,
    tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db),
):
    """Apply one transition to up to 200 legal entities; per-id outcomes."""
    spec = WORKFLOW_SPECS.get(entity_type)
    if not spec:
        raise HTTPException(404, detail=f"Unknown workflow entity '{entity_type}'. Known: {sorted(WORKFLOW_SPECS)}")
    return await apply_bulk_transition(db, spec, body.ids, body.to_state, tenant, note=body.note)
