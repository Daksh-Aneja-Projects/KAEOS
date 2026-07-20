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
from app.legal.models.core import LegalMatter
from app.legal.models.contracts import Contract, ContractClause
from app.legal.models.compliance import ComplianceObligation
from app.legal.models.litigation import Case, CaseStage
from app.legal.models.ip import Patent
from app.legal.models.privacy import DataSubjectRequest

# Agents
from app.legal.agents.contract_review_agent import ContractReviewAgent
from app.legal.agents.compliance_audit_agent import ComplianceAuditAgent
from app.legal.agents.litigation_agent import LitigationAgent
from app.legal.agents.privacy_dsar_agent import PrivacyDSARAgent
from app.legal.agents.ip_agent import IPAgent

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

    # Pending DSARs
    dsar_q = await db.execute(
        select(sqlfunc.count()).select_from(DataSubjectRequest).where(DataSubjectRequest.tenant_id == tenant_id)
        .where(DataSubjectRequest.status == "RECEIVED")
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
    q = await db.execute(select(LegalMatter).where(LegalMatter.tenant_id == tenant_id).limit(200))
    matters = q.scalars().all()
    return [{"id": m.id, "title": m.title, "type": m.matter_type, "status": m.status.value, "priority": m.priority.value, "exposure": m.estimated_exposure} for m in matters]

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
