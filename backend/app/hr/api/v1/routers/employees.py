"""KAEOS HR V1 — employees

Core employee reads (the employee directory and one employee).
"""
from typing import List, Dict, Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.tenant import get_tenant_id
from app.hr.models.core import HREmployee

router = APIRouter()


# ── Core Employee Data ────────────────────────────────────────────────────────

@router.get("/employees", response_model=List[Dict[str, Any]])
async def list_employees(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    q = await db.execute(select(HREmployee).where(HREmployee.tenant_id == tenant_id).limit(200))
    employees = q.scalars().all()
    return [{
        "id": e.id, "first_name": e.first_name, "last_name": e.last_name, "status": e.status,
        "email": e.email, "job_title": e.job_title,
        "location": e.location or ("Remote" if e.is_remote else None),
        "hire_date": e.hire_date.isoformat() if e.hire_date else None,
    } for e in employees]


@router.get("/employees/{employee_id}")
async def get_employee(employee_id: str, tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    q = await db.execute(
        select(HREmployee).where(HREmployee.tenant_id == tenant_id, HREmployee.id == employee_id)
    )
    employee = q.scalar_one_or_none()
    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found")
    return {
        "id": employee.id, "email": employee.email,
        "first_name": employee.first_name, "last_name": employee.last_name,
        "status": employee.status, "job_title": employee.job_title,
        # "title" kept for legacy consumers
        "title": employee.job_title,
        "location": employee.location or ("Remote" if employee.is_remote else None),
        "hire_date": employee.hire_date.isoformat() if employee.hire_date else None,
    }
