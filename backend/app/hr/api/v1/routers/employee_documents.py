"""KAEOS HR V1 — employee documents

Employee documents and their signature state.
"""
from datetime import date as _date, datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import record_security_event
from app.core.database import get_db
from app.core.department_endpoints import get_or_404
from app.core.tenant import approver_identity, get_tenant_id, require_role
from app.hr.models.core import HREmployee, EmployeeDocument

router = APIRouter()


# ── Employee Documents ─────────────────────────────────────────────────────────

class EmployeeDocumentCreate(BaseModel):
    employee_id: str
    doc_type: str = Field(..., pattern="^(I9|W4|OFFER_LETTER|HANDBOOK_ACK|PERFORMANCE_REVIEW|DISCIPLINARY|OTHER)$")
    title: str
    file_path: str
    is_pii: bool = True
    expiration_date: Optional[_date] = None


@router.get("/employee-documents")
async def list_employee_documents(
    employee_id: Optional[str] = None,
    tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db),
):
    stmt = select(EmployeeDocument).where(EmployeeDocument.tenant_id == tenant_id)
    if employee_id:
        stmt = stmt.where(EmployeeDocument.employee_id == employee_id)
    rows = (await db.execute(stmt.order_by(EmployeeDocument.uploaded_at.desc()).limit(200))).scalars().all()
    return [{
        "id": d.id, "employee_id": d.employee_id,
        "doc_type": d.doc_type.value if hasattr(d.doc_type, "value") else str(d.doc_type),
        "title": d.title, "is_signed": d.is_signed,
        "signature_date": d.signature_date.isoformat() if d.signature_date else None,
        "expiration_date": d.expiration_date.isoformat() if d.expiration_date else None,
        "uploaded_at": d.uploaded_at.isoformat() if d.uploaded_at else None,
    } for d in rows]


@router.post("/employee-documents", status_code=201)
async def create_employee_document(
    body: EmployeeDocumentCreate, tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db),
):
    tenant_id = tenant["tenant_id"]
    await get_or_404(db, HREmployee, body.employee_id, tenant_id, detail="Employee not found")
    doc = EmployeeDocument(
        tenant_id=tenant_id, employee_id=body.employee_id, doc_type=body.doc_type, title=body.title,
        file_path=body.file_path, is_pii=body.is_pii, expiration_date=body.expiration_date,
    )
    db.add(doc)
    await db.commit()
    await db.refresh(doc)
    await record_security_event(tenant_id=tenant_id, event_type="MODIFICATION", action="WRITE",
        actor=approver_identity(tenant), actor_role=tenant.get("role"),
        resource_type="employee_document", resource_id=doc.id)
    return {"id": doc.id, "title": doc.title}


@router.post("/employee-documents/{document_id}/sign")
async def sign_employee_document(
    document_id: str, tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db),
):
    tenant_id = tenant["tenant_id"]
    doc = await get_or_404(db, EmployeeDocument, document_id, tenant_id, detail="Document not found")
    doc.is_signed = True
    doc.signature_date = datetime.now(timezone.utc)
    db.add(doc)
    await db.commit()
    await record_security_event(tenant_id=tenant_id, event_type="MODIFICATION", action="WRITE",
        actor=approver_identity(tenant), actor_role=tenant.get("role"),
        resource_type="employee_document", resource_id=document_id)
    return {"id": document_id, "is_signed": True}
