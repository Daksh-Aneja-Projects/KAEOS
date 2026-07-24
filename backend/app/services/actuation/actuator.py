"""The Actuator — governed, idempotent, reversible write-back to a system of record.

Every outbound mutation:
  1. is keyed by a deterministic idempotency key (a retry is a no-op that returns
     the original record, never a duplicate write),
  2. applies to a real backing SorObject row (create / merge-update / soft-delete),
  3. captures before/after state and registers a compensator (the exact inverse),
  4. is appended to the provenance hash-chain, and
  5. is recorded in the Actions Ledger (ActionRecord).

Reversal replays the compensator, so any action KAEOS took can be safely undone.
This is the substrate for "autonomy that DOES": agents call the Actuator instead
of only recommending, and the write inherits the 7-gate governance of the caller.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.actuation import SorObject, ActionRecord

_VALID_OPS = {"CREATE", "UPDATE", "DELETE"}


class ActuationError(Exception):
    """Raised when an actuation request is malformed or cannot be reversed."""


def _idempotency_key(tenant_id: str, system: str, object_type: str,
                     external_id: str, operation: str, payload: dict) -> str:
    raw = json.dumps(
        {"t": tenant_id, "s": system, "o": object_type, "e": external_id,
         "op": operation, "p": payload or {}},
        sort_keys=True, default=str,
    )
    return hashlib.sha256(raw.encode()).hexdigest()[:48]


async def _record_provenance(db: AsyncSession, tenant_id: str, actor: str,
                             action: str, payload: dict) -> Optional[str]:
    """Append to the provenance hash-chain; never fatal to the actuation."""
    try:
        from app.services.quantum_ledger import QuantumLedgerEngine
        entry = await QuantumLedgerEngine.record_quantum_event(
            db=db, event_type=f"ACTUATION_{action}", actor=actor or "system",
            reasoning=f"Governed SoR write: {action}",
            payload={**payload, "tenant_id": tenant_id},
        )
        return getattr(entry, "id", None)
    except Exception:
        return None


class Actuator:
    """Stateless helper; all state lives in the DB (SorObject + ActionRecord)."""

    @staticmethod
    async def apply_action(
        db: AsyncSession,
        *,
        tenant_id: str,
        system: str,
        object_type: str,
        external_id: str,
        operation: str,
        payload: Optional[dict] = None,
        execution_id: Optional[str] = None,
        actor: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> ActionRecord:
        operation = (operation or "").strip().upper()
        if operation not in _VALID_OPS:
            raise ActuationError(f"operation must be one of {sorted(_VALID_OPS)}")
        payload = payload or {}
        key = idempotency_key or _idempotency_key(
            tenant_id, system, object_type, external_id, operation, payload)

        # Idempotency: a prior APPLIED action with this key is returned as-is.
        existing = (await db.execute(
            select(ActionRecord).where(
                ActionRecord.tenant_id == tenant_id,
                ActionRecord.idempotency_key == key,
            )
        )).scalar_one_or_none()
        if existing is not None and existing.status == "APPLIED":
            return existing

        # Load (or prepare) the backing SoR object.
        obj = (await db.execute(
            select(SorObject).where(
                SorObject.tenant_id == tenant_id,
                SorObject.system == system,
                SorObject.object_type == object_type,
                SorObject.external_id == external_id,
            )
        )).scalar_one_or_none()

        before_state: Optional[dict] = None
        after_state: Optional[dict] = None
        compensator: dict = {}

        if operation == "CREATE":
            if obj is not None and not obj.deleted:
                raise ActuationError(
                    f"{object_type}:{external_id} already exists in {system}")
            if obj is None:
                obj = SorObject(tenant_id=tenant_id, system=system,
                                object_type=object_type, external_id=external_id,
                                state={}, version=0, deleted=0)
                db.add(obj)
            before_state = None
            obj.state = dict(payload)
            obj.deleted = 0
            obj.version = (obj.version or 0) + 1
            after_state = dict(obj.state)
            # Inverse of a create is a delete.
            compensator = {"operation": "DELETE", "payload": {}}

        elif operation == "UPDATE":
            if obj is None or obj.deleted:
                raise ActuationError(
                    f"{object_type}:{external_id} not found in {system}")
            before_state = dict(obj.state or {})
            merged = dict(obj.state or {})
            merged.update(payload)
            obj.state = merged
            obj.version = (obj.version or 0) + 1
            after_state = dict(obj.state)
            # Inverse of an update restores the exact prior field values.
            compensator = {"operation": "UPDATE", "payload": before_state}

        elif operation == "DELETE":
            if obj is None or obj.deleted:
                raise ActuationError(
                    f"{object_type}:{external_id} not found in {system}")
            before_state = dict(obj.state or {})
            obj.deleted = 1
            obj.version = (obj.version or 0) + 1
            after_state = None
            # Inverse of a delete re-creates the exact prior record.
            compensator = {"operation": "CREATE", "payload": before_state}

        prov_id = await _record_provenance(
            db, tenant_id, actor or "system", operation,
            {"system": system, "object_type": object_type,
             "external_id": external_id, "operation": operation},
        )

        record = ActionRecord(
            tenant_id=tenant_id, execution_id=execution_id,
            system=system, object_type=object_type, external_id=external_id,
            operation=operation, idempotency_key=key, request_payload=payload,
            before_state=before_state, after_state=after_state,
            compensator=compensator, status="APPLIED",
            provenance_id=prov_id, actor=actor,
        )
        db.add(record)
        await db.commit()
        await db.refresh(record)
        return record

    @staticmethod
    async def reverse_action(
        db: AsyncSession, *, tenant_id: str, action_id: str,
        actor: Optional[str] = None,
    ) -> ActionRecord:
        record = (await db.execute(
            select(ActionRecord).where(
                ActionRecord.id == action_id, ActionRecord.tenant_id == tenant_id)
        )).scalar_one_or_none()
        if record is None:
            raise ActuationError("action not found")
        if record.status != "APPLIED":
            raise ActuationError(f"action is {record.status}, only APPLIED can be reversed")

        comp = record.compensator or {}
        comp_op = (comp.get("operation") or "").upper()
        comp_payload = comp.get("payload") or {}

        obj = (await db.execute(
            select(SorObject).where(
                SorObject.tenant_id == tenant_id,
                SorObject.system == record.system,
                SorObject.object_type == record.object_type,
                SorObject.external_id == record.external_id,
            )
        )).scalar_one_or_none()
        if obj is None:
            raise ActuationError("backing object vanished; cannot reverse safely")

        if comp_op == "DELETE":
            obj.deleted = 1
        elif comp_op == "CREATE":
            obj.state = dict(comp_payload)
            obj.deleted = 0
        elif comp_op == "UPDATE":
            obj.state = dict(comp_payload)
            obj.deleted = 0
        else:
            raise ActuationError("action has no valid compensator")
        obj.version = (obj.version or 0) + 1

        prov_id = await _record_provenance(
            db, tenant_id, actor or "system", "REVERSE",
            {"reversed_action": record.id, "system": record.system,
             "external_id": record.external_id},
        )

        record.status = "REVERSED"
        record.reversed_at = datetime.now(timezone.utc)
        if prov_id:
            record.provenance_id = record.provenance_id or prov_id
        await db.commit()
        await db.refresh(record)
        return record

    @staticmethod
    async def compute_drift(db: AsyncSession, *, tenant_id: str) -> dict:
        """Reconcile the SoR against the actions that governed it.

        Drift = a live SoR object whose last modification is newer than the most
        recent governing action for it (i.e. something changed the record outside
        the actuation path). In a fully governed world drift is zero; when it is
        not, these are exactly the rows to reconcile.
        """
        objs = (await db.execute(
            select(SorObject).where(SorObject.tenant_id == tenant_id)
        )).scalars().all()

        drifted = []
        for o in objs:
            if o.deleted:
                continue
            actions = (await db.execute(
                select(ActionRecord).where(
                    ActionRecord.tenant_id == tenant_id,
                    ActionRecord.system == o.system,
                    ActionRecord.object_type == o.object_type,
                    ActionRecord.external_id == o.external_id,
                )
            )).scalars().all()

            governed = len(actions) > 0
            # The most recent GOVERNED touch is the latest of any action's create
            # or reverse time — a reversal is itself a governed modification, so it
            # must not read as drift.
            last_touch = None
            for a in actions:
                for ts in (a.created_at, a.reversed_at):
                    if ts and (last_touch is None or ts > last_touch):
                        last_touch = ts

            stale = False
            if governed and last_touch and o.updated_at:
                # Tolerate clock skew; only flag a clear post-action modification.
                stale = o.updated_at > last_touch and \
                    (o.updated_at - last_touch).total_seconds() > 1.0
            if not governed or stale:
                drifted.append({
                    "system": o.system, "object_type": o.object_type,
                    "external_id": o.external_id, "version": o.version,
                    "reason": "untracked_write" if not governed else "post_action_modification",
                })

        total_live = sum(1 for o in objs if not o.deleted)
        return {
            "objects_tracked": total_live,
            "in_sync": total_live - len(drifted),
            "drift_count": len(drifted),
            "drift": drifted,
            "note": "Drift = SoR rows changed outside the governed actuation path.",
        }
