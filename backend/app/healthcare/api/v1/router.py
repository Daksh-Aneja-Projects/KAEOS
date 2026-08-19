"""
KAEOS Healthcare Domain — V1 API Router

Clinical operations endpoints. The /disclosures create path runs the fail-closed
HIPAA + 42 CFR Part 2 gate before any PHI leaves the building: a disclosure that
violates minimum-necessary or lacks authorization is refused (422) and never
recorded.
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func as sqlfunc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import record_security_event
from app.core.department_endpoints import get_or_404, make_department_workflow_router
from app.core.database import get_db
from app.core.tenant import approver_identity, get_tenant_id, require_role
from app.healthcare.models.compliance import ComplianceReport
from app.healthcare.models.core import (
    ClinicalTask, ConsentRecord, PatientEncounter, PHIDisclosure,
)
from app.healthcare.services.analytics import healthcare_analytics
from app.healthcare.services.phi_disclosure import resolve_consent_facts
from app.healthcare.services.workflows import SPECS as WORKFLOW_SPECS

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/healthcare", tags=["Healthcare"])


# ─── Dashboard ────────────────────────────────────────────────────────────

@router.get("/dashboard")
async def healthcare_dashboard(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    async def _count(model, *where):
        q = select(sqlfunc.count()).select_from(model).where(model.tenant_id == tenant_id, *where)
        return int((await db.execute(q)).scalar() or 0)

    open_enc = await _count(PatientEncounter, PatientEncounter.status.in_(["OPEN", "TRIAGED"]))
    return {
        "total_encounters": await _count(PatientEncounter),
        "open_encounters": open_enc,
        "phi_disclosures": await _count(PHIDisclosure),
        "active_consents": await _count(ConsentRecord, ConsentRecord.revoked_at.is_(None)),
        "open_clinical_tasks": await _count(ClinicalTask, ClinicalTask.status != "DONE"),
    }


@router.get("/analytics")
async def get_healthcare_analytics(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    """Computed KPIs, distributions and insights for the healthcare cockpit."""
    return await healthcare_analytics(db, tenant_id)


# Generated from the shared factory in app/core/department_endpoints.py.
# Endpoint names and docstrings are the hand-written originals, so the
# operationIds and descriptions in the OpenAPI schema are unchanged.
router.include_router(make_department_workflow_router(
    "healthcare", WORKFLOW_SPECS,
    workflows_doc='Declared state machines — the frontend renders transition actions from this.',
))


@router.get("/compliance-reports")
async def list_compliance_reports(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(
        select(ComplianceReport).where(ComplianceReport.tenant_id == tenant_id)
        .order_by(ComplianceReport.generated_at.desc()).limit(50))).scalars().all()
    return [{"id": r.id, "framework": r.framework, "report_name": r.report_name,
             "period_year": r.period_year, "status": r.status,
             "generated_at": r.generated_at.isoformat() if r.generated_at else None,
             "submitted_at": r.submitted_at.isoformat() if r.submitted_at else None,
             "data": r.data} for r in rows]


# ─── Encounters ───────────────────────────────────────────────────────────

def _enc_dict(e: PatientEncounter) -> dict:
    return {"id": e.id, "encounter_number": e.encounter_number, "patient_ref": e.patient_ref,
            "type": e.encounter_type, "status": e.status, "reason": e.reason,
            "priority": e.priority, "diagnosis_codes": e.diagnosis_codes or []}


@router.get("/encounters")
async def list_encounters(status: Optional[str] = None, tenant_id: str = Depends(get_tenant_id),
                          db: AsyncSession = Depends(get_db)):
    q = select(PatientEncounter).where(PatientEncounter.tenant_id == tenant_id)
    if status:
        q = q.where(PatientEncounter.status == status)
    rows = (await db.execute(q.order_by(PatientEncounter.created_at.desc()).limit(200))).scalars().all()
    return [_enc_dict(e) for e in rows]


class EncounterCreate(BaseModel):
    patient_ref: str = Field(..., min_length=1, max_length=64)
    encounter_type: str = Field(..., max_length=32)
    reason: Optional[str] = Field(None, max_length=256)


@router.post("/encounters", status_code=201)
async def create_encounter(body: EncounterCreate, tenant: dict = Depends(require_role("operator")),
                           db: AsyncSession = Depends(get_db)):
    import uuid as _uuid
    tenant_id = tenant["tenant_id"]
    enc = PatientEncounter(
        tenant_id=tenant_id, encounter_number=f"ENC-{_uuid.uuid4().hex[:8].upper()}",
        patient_ref=body.patient_ref, encounter_type=body.encounter_type,
        reason=body.reason, status="OPEN",
    )
    db.add(enc)
    await db.commit()
    await db.refresh(enc)
    await record_security_event(
        tenant_id=tenant_id, event_type="MODIFICATION", action="WRITE",
        actor=tenant.get("email") or tenant.get("name"), actor_role=tenant.get("role"),
        resource_type="encounter", resource_id=enc.id,
    )
    return _enc_dict(enc)


# ─── Encounter agent actions (the gated 7-gate pipeline, live) ────────────
#
# Every write here goes through app.healthcare.agents.gated_runner's
# run_gated_healthcare_skill: Compliance -> Fairness -> Confidence/HITL ->
# Debate -> Execute -> Audit. always_hitl=True on every healthcare skill means
# a clean run still lands on PENDING_HITL - that is the expected, governed
# outcome, not a failure.

class PriorAuthRequest(BaseModel):
    procedure: str = Field(..., min_length=1, max_length=256)
    payer: Optional[str] = Field(None, max_length=128)


# REVIEW: healthcare's gated agent endpoints map ValueError -> 404 but have no
# 500 handler, record the audit event OUTSIDE the try, and raise
# HTTPException(404, str(e)) positionally instead of detail=str(e). Kept
# hand-written; adding the 500 handler is a behaviour change. Healthcare also
# has no /workflow-events and no bulk-transition endpoint (see the single
# make_department_workflow_router() mount below).
@router.post("/encounters/{encounter_id}/triage")
async def triage_encounter_route(encounter_id: str, tenant: dict = Depends(require_role("operator")),
                                 db: AsyncSession = Depends(get_db)):
    """Runs the Intake Agent's deterministic triage through the gated pipeline."""
    from app.healthcare.agents.intake_agent import IntakeAgent
    try:
        result = await IntakeAgent().triage_encounter(db, encounter_id, tenant)
    except ValueError as e:
        raise HTTPException(404, str(e))
    await record_security_event(
        tenant_id=tenant["tenant_id"], event_type="MODIFICATION", action="EXECUTE",
        actor=tenant.get("email") or tenant.get("name"), actor_role=tenant.get("role"),
        resource_type="encounter", resource_id=encounter_id,
    )
    return result


@router.post("/encounters/{encounter_id}/suggest-codes")
async def suggest_codes_route(encounter_id: str, tenant: dict = Depends(require_role("operator")),
                              db: AsyncSession = Depends(get_db)):
    """Runs the Medical Coding Agent's ICD-10 suggestion through the gated pipeline."""
    from app.healthcare.agents.coding_agent import CodingAgent
    try:
        result = await CodingAgent().suggest_codes(db, encounter_id, tenant)
    except ValueError as e:
        raise HTTPException(404, str(e))
    await record_security_event(
        tenant_id=tenant["tenant_id"], event_type="MODIFICATION", action="EXECUTE",
        actor=tenant.get("email") or tenant.get("name"), actor_role=tenant.get("role"),
        resource_type="clinical_task", resource_id=result.get("task_id"),
    )
    return result


@router.post("/encounters/{encounter_id}/prior-auth")
async def prior_auth_route(encounter_id: str, body: PriorAuthRequest,
                           tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db)):
    """Runs the Prior Authorization Agent's justification draft through the gated pipeline."""
    from app.healthcare.agents.prior_auth_agent import PriorAuthAgent
    try:
        result = await PriorAuthAgent().prepare_prior_auth(
            db, tenant, encounter_id=encounter_id, procedure=body.procedure, payer=body.payer)
    except ValueError as e:
        raise HTTPException(404, str(e))
    await record_security_event(
        tenant_id=tenant["tenant_id"], event_type="MODIFICATION", action="EXECUTE",
        actor=tenant.get("email") or tenant.get("name"), actor_role=tenant.get("role"),
        resource_type="clinical_task", resource_id=result.get("task_id"),
    )
    return result


# ─── PHI Disclosures (the gated write path) ───────────────────────────────

class DisclosureCreate(BaseModel):
    purpose: str = Field(..., max_length=48)
    recipient: str = Field(..., min_length=1, max_length=128)
    fields: list[str] = Field(default_factory=list)
    minimum_necessary_justification: str = Field(..., min_length=1)
    encounter_id: Optional[str] = None
    diagnosis_codes: list[str] = Field(default_factory=list)
    part2_records: bool = False
    # Authorization / consent facts the checkers read. Client-supplied because a
    # real deployment binds these from the consent store; the gate verifies them.
    authorization: Optional[dict] = None
    part2_consent: Optional[dict] = None


@router.get("/disclosures")
async def list_disclosures(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(
        select(PHIDisclosure).where(PHIDisclosure.tenant_id == tenant_id)
        .order_by(PHIDisclosure.created_at.desc()).limit(200))).scalars().all()
    return [{"id": d.id, "purpose": d.purpose, "recipient": d.recipient,
             "fields": d.fields or [], "part2": d.part2, "authorized": d.authorized,
             "justification": d.minimum_necessary_justification,
             "encounter_id": d.encounter_id} for d in rows]


@router.post("/disclosures", status_code=201)
async def create_disclosure(body: DisclosureCreate, tenant: dict = Depends(require_role("operator")),
                            db: AsyncSession = Depends(get_db)):
    """Record a PHI disclosure - ONLY if it passes the HIPAA + Part 2 gate.

    Routed through PHIGuardAgent.review_disclosure: the deterministic HIPAA +
    Part 2 checkers run FIRST (the load-bearing control, unchanged), then the
    full 7-gate AgentExecutor pipeline governs the release. A disclosure
    exceeding minimum-necessary scope, lacking a required patient
    authorization, touching Part 2 substance-use records without consent, or
    blocked at a governance gate is refused (422) and never persisted; the
    denial is written to the ledger."""
    from app.healthcare.agents.phi_guard_agent import PHIGuardAgent

    tenant_id = tenant["tenant_id"]
    # The gate's consent facts default to the request body ONLY for an ad-hoc,
    # encounter-less disclosure. When the disclosure is bound to an encounter,
    # the encounter's stored SUD codes and the patient's ACTIVE consent records
    # are the source of truth: the body may strengthen the verdict but never
    # weaken it (a revoked consent stays revoked, an omitted SUD code still
    # triggers Part 2). Otherwise consent revocation would have no teeth.
    authorization, diagnosis_codes, part2_consent = (
        body.authorization, body.diagnosis_codes, body.part2_consent)
    if body.encounter_id:
        # Validate the encounter belongs to this tenant (404, not 403, on a foreign id).
        enc = (await db.execute(select(
            PatientEncounter.patient_ref, PatientEncounter.diagnosis_codes).where(
            PatientEncounter.id == body.encounter_id,
            PatientEncounter.tenant_id == tenant_id))).one_or_none()
        if not enc:
            raise HTTPException(404, "Encounter not found")
        consents = (await db.execute(select(
            ConsentRecord.scope, ConsentRecord.part2, ConsentRecord.revoked_at).where(
            ConsentRecord.tenant_id == tenant_id,
            ConsentRecord.patient_ref == enc.patient_ref))).all()
        resolved = resolve_consent_facts(
            purpose=body.purpose,
            stored_diagnosis_codes=enc.diagnosis_codes or [],
            stored_consents=[{"scope": c.scope, "part2": c.part2,
                              "active": c.revoked_at is None} for c in consents],
            diagnosis_codes=body.diagnosis_codes,
            authorization=body.authorization,
            part2_consent=body.part2_consent,
        )
        authorization = resolved["authorization"]
        diagnosis_codes = resolved["diagnosis_codes"]
        part2_consent = resolved["part2_consent"]

    result = await PHIGuardAgent().review_disclosure(
        db, tenant_id,
        purpose=body.purpose, recipient=body.recipient, fields=body.fields,
        minimum_necessary_justification=body.minimum_necessary_justification,
        encounter_id=body.encounter_id, authorization=authorization,
        diagnosis_codes=diagnosis_codes, part2_records=body.part2_records,
        part2_consent=part2_consent, recorded_by=approver_identity(tenant),
    )
    if not result.get("recorded"):
        # Governance refusal - surface WHY, keep it a 422 (the request was well
        # formed; the disclosure is simply not permitted).
        raise HTTPException(422, detail={"error": "PHI disclosure blocked",
                                         "reason": result.get("reason") or "Blocked by the governance gate.",
                                         "blocking": result.get("blocking", []),
                                         "gate_status": result.get("status")})
    disclosure = (await db.execute(select(PHIDisclosure).where(
        PHIDisclosure.id == result["disclosure_id"]))).scalar_one()
    await record_security_event(
        tenant_id=tenant_id, event_type="MODIFICATION", action="WRITE",
        actor=tenant.get("email") or tenant.get("name"), actor_role=tenant.get("role"),
        resource_type="phi_disclosure", resource_id=disclosure.id,
    )
    return {"id": disclosure.id, "purpose": disclosure.purpose, "recipient": disclosure.recipient,
            "authorized": disclosure.authorized, "part2": disclosure.part2,
            "gate_status": result.get("gate_status"), "execution_id": result.get("execution_id")}


# ─── Consent ──────────────────────────────────────────────────────────────

class ConsentCreate(BaseModel):
    patient_ref: str = Field(..., min_length=1, max_length=64)
    scope: str = Field(..., max_length=64)
    part2: bool = False


@router.get("/consent")
async def list_consent(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(
        select(ConsentRecord).where(ConsentRecord.tenant_id == tenant_id)
        .order_by(ConsentRecord.created_at.desc()).limit(200))).scalars().all()
    return [{"id": c.id, "patient_ref": c.patient_ref, "scope": c.scope, "part2": c.part2,
             "active": c.revoked_at is None,
             "granted_at": c.granted_at.isoformat() if c.granted_at else None,
             "revoked_at": c.revoked_at.isoformat() if c.revoked_at else None} for c in rows]


@router.post("/consent", status_code=201)
async def create_consent(body: ConsentCreate, tenant: dict = Depends(require_role("operator")),
                         db: AsyncSession = Depends(get_db)):
    tenant_id = tenant["tenant_id"]
    c = ConsentRecord(tenant_id=tenant_id, patient_ref=body.patient_ref,
                      scope=body.scope, part2=body.part2)
    db.add(c)
    await db.commit()
    await db.refresh(c)
    return {"id": c.id, "patient_ref": c.patient_ref, "scope": c.scope, "part2": c.part2, "active": True}


@router.post("/consent/{consent_id}/revoke")
async def revoke_consent(consent_id: str, tenant: dict = Depends(require_role("operator")),
                         db: AsyncSession = Depends(get_db)):
    from datetime import datetime, timezone
    tenant_id = tenant["tenant_id"]
    c = await get_or_404(db, ConsentRecord, consent_id, tenant_id, detail="Consent not found")
    if c.revoked_at is None:
        c.revoked_at = datetime.now(timezone.utc)
        db.add(c)
        await db.commit()
    return {"id": c.id, "active": False}


# ─── Clinical Tasks ───────────────────────────────────────────────────────

class TaskCreate(BaseModel):
    task_type: str = Field(..., max_length=32)
    encounter_id: Optional[str] = None
    assignee: Optional[str] = Field(None, max_length=64)


@router.get("/tasks")
async def list_tasks(status: Optional[str] = None, tenant_id: str = Depends(get_tenant_id),
                     db: AsyncSession = Depends(get_db)):
    q = select(ClinicalTask).where(ClinicalTask.tenant_id == tenant_id)
    if status:
        q = q.where(ClinicalTask.status == status)
    rows = (await db.execute(q.order_by(ClinicalTask.created_at.desc()).limit(200))).scalars().all()
    return [{"id": t.id, "type": t.task_type, "status": t.status, "assignee": t.assignee,
             "encounter_id": t.encounter_id, "detail": t.detail or {}} for t in rows]


@router.post("/tasks", status_code=201)
async def create_task(body: TaskCreate, tenant: dict = Depends(require_role("operator")),
                      db: AsyncSession = Depends(get_db)):
    tenant_id = tenant["tenant_id"]
    if body.encounter_id:
        enc = (await db.execute(select(PatientEncounter.id).where(
            PatientEncounter.id == body.encounter_id,
            PatientEncounter.tenant_id == tenant_id))).scalar_one_or_none()
        if not enc:
            raise HTTPException(404, "Encounter not found")
    t = ClinicalTask(tenant_id=tenant_id, task_type=body.task_type,
                     encounter_id=body.encounter_id, assignee=body.assignee, status="OPEN")
    db.add(t)
    await db.commit()
    await db.refresh(t)
    return {"id": t.id, "type": t.task_type, "status": t.status}
