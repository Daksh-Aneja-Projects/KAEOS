"""System-of-Record actuation API (v3 Phase 1).

The Actions Ledger: governed, idempotent, reversible write-back to a system of
record, distinct from the provenance *decision* ledger. Operators (and agents,
via the Actuator) issue governed writes; anyone with read access sees what KAEOS
actually DID and can reverse it.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, func, case
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.tenant import get_tenant_id, require_role
from app.core.audit import record_security_event
from app.models.actuation import ActionRecord
from app.services.actuation import Actuator, ActuationError

router = APIRouter(prefix="/actuation", tags=["Actuation"])


class ActionIn(BaseModel):
    system: str
    object_type: str
    external_id: str
    operation: str                       # CREATE | UPDATE | DELETE
    payload: dict = {}
    execution_id: Optional[str] = None
    idempotency_key: Optional[str] = None


def _to_dict(r: ActionRecord) -> dict:
    return {
        "id": r.id,
        "execution_id": r.execution_id,
        "system": r.system,
        "object_type": r.object_type,
        "external_id": r.external_id,
        "operation": r.operation,
        "status": r.status,
        "actor": r.actor,
        "provenance_id": r.provenance_id,
        "reversible": r.status == "APPLIED" and bool(r.compensator),
        "before_state": r.before_state,
        "after_state": r.after_state,
        "error": r.error,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "reversed_at": r.reversed_at.isoformat() if r.reversed_at else None,
    }


@router.post("/execute")
async def execute_action(
    body: ActionIn,
    tenant: dict = Depends(require_role("operator")),
    db: AsyncSession = Depends(get_db),
):
    """Perform a governed write to a system of record. Idempotent on retry and
    reversible: the action carries an idempotency key, provenance id, and a
    compensator computed from the captured before-state."""
    tenant_id = tenant["tenant_id"]
    try:
        record = await Actuator.apply_action(
            db, tenant_id=tenant_id, system=body.system,
            object_type=body.object_type, external_id=body.external_id,
            operation=body.operation, payload=body.payload,
            execution_id=body.execution_id, actor=tenant.get("name"),
            idempotency_key=body.idempotency_key,
        )
    except ActuationError as e:
        raise HTTPException(status_code=400, detail=str(e))

    await record_security_event(
        tenant_id=tenant_id, event_type="ACTUATION", action=record.operation,
        actor=tenant.get("name"), actor_role=tenant.get("role"),
        resource_type=f"{body.system}:{body.object_type}", resource_id=body.external_id,
        details={"action_id": record.id, "status": record.status},
    )
    return _to_dict(record)


@router.post("/{action_id}/reverse")
async def reverse_action(
    action_id: str,
    tenant: dict = Depends(require_role("operator")),
    db: AsyncSession = Depends(get_db),
):
    """Reverse a previously applied action by replaying its compensator."""
    tenant_id = tenant["tenant_id"]
    try:
        record = await Actuator.reverse_action(
            db, tenant_id=tenant_id, action_id=action_id, actor=tenant.get("name"))
    except ActuationError as e:
        raise HTTPException(status_code=400, detail=str(e))

    await record_security_event(
        tenant_id=tenant_id, event_type="ACTUATION", action="REVERSE",
        actor=tenant.get("name"), actor_role=tenant.get("role"),
        resource_type=f"{record.system}:{record.object_type}", resource_id=record.external_id,
        details={"action_id": record.id, "status": record.status},
    )
    return _to_dict(record)


@router.get("/ledger")
async def actions_ledger(
    limit: int = 50,
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """Recent governed actions with a status summary. Real records only."""
    limit = max(1, min(200, limit))
    scope = ActionRecord.tenant_id == tenant_id

    applied = func.count(case((ActionRecord.status == "APPLIED", 1)))
    reversed_ = func.count(case((ActionRecord.status == "REVERSED", 1)))
    failed = func.count(case((ActionRecord.status == "FAILED", 1)))
    row = (await db.execute(select(func.count(), applied, reversed_, failed).where(scope))).one()

    rows = (await db.execute(
        select(ActionRecord).where(scope)
        .order_by(ActionRecord.created_at.desc()).limit(limit)
    )).scalars().all()

    return {
        "summary": {"total": int(row[0] or 0), "applied": int(row[1] or 0),
                    "reversed": int(row[2] or 0), "failed": int(row[3] or 0)},
        "actions": [_to_dict(r) for r in rows],
        "note": "The Actions Ledger records what KAEOS DID to a system of record (reversible), distinct from the decision ledger.",
    }


@router.get("/drift")
async def actuation_drift(
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """Reconcile the sandbox system of record against the governing actions."""
    return await Actuator.compute_drift(db, tenant_id=tenant_id)
