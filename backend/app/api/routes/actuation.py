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
from app.core.tenant import approver_identity

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
    compensator computed from the captured before-state.

    Consequence gate at the actuation boundary: this route used to be the one
    execution path with NO gate at all - one API call could delete data or move
    money. High-consequence writes (the same shared is_high_consequence rule
    Gate 3 and /skills enforce) now pause in the HITL queue and apply only
    after human approval, fail-closed, via the same resume path as every other
    approval."""
    tenant_id = tenant["tenant_id"]

    from app.services.consequence import is_high_consequence
    _probe = {
        "skill_id": f"actuation.{body.system}.{body.object_type}.{body.operation}".lower(),
        "tags": ["data_deletion"] if body.operation.upper() == "DELETE" else [],
    }
    if is_high_consequence(_probe):
        import uuid as _uuid

        from app.services.hitl_manager import hitl_manager
        exec_id = f"exec-{_uuid.uuid4().hex[:8]}"
        target = f"{body.system}:{body.object_type}/{body.external_id}"
        await hitl_manager.request_human_confirmation(
            skill={
                "skill_id": _probe["skill_id"],
                # One LLM-free step so the resumed run finalizes the row.
                "steps": [{"id": "approved", "action": "log",
                           "message": f"Approved governed write to {target}."}],
                "compliance_tags": [], "department": "operations",
                "actuation": {
                    "system": body.system, "object_type": body.object_type,
                    "external_id": body.external_id, "operation": body.operation,
                    "payload": body.payload,
                    "idempotency_key": body.idempotency_key,
                },
            },
            context={
                "execution_id": exec_id, "tenant_id": tenant_id,
                "intent": f"{body.operation} {target}",
                "requested_by": tenant.get("email") or tenant.get("name") or "operator",
                # Also on the durable DB row: the write must still apply if the
                # 24h gate-cache record expires before someone approves.
                "actuation": {
                    "system": body.system, "object_type": body.object_type,
                    "external_id": body.external_id, "operation": body.operation,
                    "payload": body.payload,
                    "idempotency_key": body.idempotency_key,
                },
            },
        )
        await record_security_event(
            tenant_id=tenant_id, event_type="ACTUATION", action="HITL_PENDING",
            actor=approver_identity(tenant), actor_role=tenant.get("role"),
            resource_type=f"{body.system}:{body.object_type}", resource_id=body.external_id,
            details={"execution_id": exec_id, "operation": body.operation},
        )
        return {
            "status": "PENDING_HITL", "execution_id": exec_id,
            "detail": (f"{body.operation} on {target} is high-consequence and "
                       "awaits human approval in the HITL queue; the write "
                       "applies only after approval."),
        }

    try:
        record = await Actuator.apply_action(
            db, tenant_id=tenant_id, system=body.system,
            object_type=body.object_type, external_id=body.external_id,
            operation=body.operation, payload=body.payload,
            execution_id=body.execution_id, actor=approver_identity(tenant),
            idempotency_key=body.idempotency_key,
        )
    except ActuationError as e:
        raise HTTPException(status_code=400, detail=str(e))

    await record_security_event(
        tenant_id=tenant_id, event_type="ACTUATION", action=record.operation,
        actor=approver_identity(tenant), actor_role=tenant.get("role"),
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
            db, tenant_id=tenant_id, action_id=action_id, actor=approver_identity(tenant))
    except ActuationError as e:
        raise HTTPException(status_code=400, detail=str(e))

    await record_security_event(
        tenant_id=tenant_id, event_type="ACTUATION", action="REVERSE",
        actor=approver_identity(tenant), actor_role=tenant.get("role"),
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


@router.get("/ledger/export")
async def actions_ledger_export(
    limit: int = 5000,
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """Download the Actions Ledger as CSV (audit/compliance evidence)."""
    from app.core.csv_export import csv_response
    limit = max(1, min(50000, limit))
    rows = (await db.execute(
        select(ActionRecord).where(ActionRecord.tenant_id == tenant_id)
        .order_by(ActionRecord.created_at.desc()).limit(limit)
    )).scalars().all()
    return csv_response([_to_dict(r) for r in rows], "actions_ledger.csv")


@router.get("/drift")
async def actuation_drift(
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """Reconcile the sandbox system of record against the governing actions."""
    return await Actuator.compute_drift(db, tenant_id=tenant_id)


@router.post("/reconcile")
async def actuation_reconcile(
    tenant: dict = Depends(require_role("operator")),
    db: AsyncSession = Depends(get_db),
):
    """L3 heal: re-assert the last governed state for every drifted object.

    Auto-healing — detection alone left drift as a dead-end read. Operator-gated;
    each re-assertion is a governed, reversible action recorded in the ledger.
    """
    tenant_id = tenant["tenant_id"]
    receipt = await Actuator.reconcile_all(db, tenant_id=tenant_id, actor=approver_identity(tenant))
    await record_security_event(
        tenant_id=tenant_id, event_type="ACTUATION", action="RECONCILE",
        actor=approver_identity(tenant), actor_role=tenant.get("role"),
        resource_type="sor", resource_id="*",
        details={"reconciled": receipt["reconciled"], "drift_count": receipt["drift_count"]},
    )
    return receipt
