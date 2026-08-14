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
from app.core.database import get_db
from app.core.tenant import approver_identity, get_tenant_id, require_role
from app.healthcare.models.core import (
    ClinicalTask, ConsentRecord, PatientEncounter, PHIDisclosure,
)
from app.healthcare.services.analytics import healthcare_analytics
from app.healthcare.services.phi_disclosure import PHIDisclosureError, record_disclosure

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

    A disclosure exceeding minimum-necessary scope, lacking a required patient
    authorization, or touching Part 2 substance-use records without consent is
    refused (422) and never persisted; the denial is written to the ledger."""
    tenant_id = tenant["tenant_id"]
    # Validate the encounter belongs to this tenant (404, not 403, on a foreign id).
    if body.encounter_id:
        enc = (await db.execute(select(PatientEncounter.id).where(
            PatientEncounter.id == body.encounter_id,
            PatientEncounter.tenant_id == tenant_id))).scalar_one_or_none()
        if not enc:
            raise HTTPException(404, "Encounter not found")
    try:
        disclosure = await record_disclosure(
            db, tenant_id,
            purpose=body.purpose, recipient=body.recipient, fields=body.fields,
            minimum_necessary_justification=body.minimum_necessary_justification,
            encounter_id=body.encounter_id, authorization=body.authorization,
            diagnosis_codes=body.diagnosis_codes, part2_records=body.part2_records,
            part2_consent=body.part2_consent, recorded_by=approver_identity(tenant),
        )
    except PHIDisclosureError as e:
        # Governance refusal - surface WHY, keep it a 422 (the request was well
        # formed; the disclosure is simply not permitted).
        raise HTTPException(422, detail={"error": "PHI disclosure blocked",
                                         "reason": str(e), "blocking": e.blocking})
    await record_security_event(
        tenant_id=tenant_id, event_type="MODIFICATION", action="WRITE",
        actor=tenant.get("email") or tenant.get("name"), actor_role=tenant.get("role"),
        resource_type="phi_disclosure", resource_id=disclosure.id,
    )
    return {"id": disclosure.id, "purpose": disclosure.purpose, "recipient": disclosure.recipient,
            "authorized": disclosure.authorized, "part2": disclosure.part2}


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
    c = (await db.execute(select(ConsentRecord).where(
        ConsentRecord.id == consent_id, ConsentRecord.tenant_id == tenant_id))).scalar_one_or_none()
    if not c:
        raise HTTPException(404, "Consent not found")
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
