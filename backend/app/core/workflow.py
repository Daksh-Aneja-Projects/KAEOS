"""
KAEOS Core — Shared Workflow Transition Engine

Every domain (Finance, HR, Sales, Support, Operations, Legal, Engineering)
exposes lifecycle actions on its core entities (approve an invoice, resolve a
ticket, advance a deal). Instead of each router hand-rolling status writes,
domains declare a WorkflowSpec (entity + allowed transition map + on-enter
hooks) and route every state change through apply_transition(), which:

  1. fetches the row tenant-scoped (404 on miss — never confirms foreign ids),
  2. validates the transition against the declared map (409 with the allowed
     next states on violation),
  3. runs the target-state hook (timestamps, derived fields),
  4. persists a WorkflowEvent audit row and a security audit event.

This keeps the state machine in one reviewable place per domain and gives the
platform a uniform, queryable transition history across all domains.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from fastapi import HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import Column, DateTime, JSON, String, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import func

from app.core.audit import record_security_event
from app.models.domain import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class WorkflowEvent(Base):
    """Cross-domain audit trail: one row per guarded state transition."""
    __tablename__ = "core_workflow_events"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)

    domain = Column(String(32), nullable=False, index=True)
    entity_type = Column(String(64), nullable=False, index=True)
    entity_id = Column(String, nullable=False, index=True)

    from_state = Column(String(64), nullable=False)
    to_state = Column(String(64), nullable=False)
    actor = Column(String(128), nullable=True)
    actor_role = Column(String(32), nullable=True)
    note = Column(String(512), nullable=True)
    context = Column(JSON, default=dict)

    created_at = Column(DateTime(timezone=True), server_default=func.now())


@dataclass
class TransitionContext:
    """Passed to on-enter hooks so they can stamp actor/time-derived fields."""
    tenant_id: str
    actor: Optional[str]
    actor_role: Optional[str]
    note: Optional[str]
    now: datetime


# Hook signature: mutate the ORM object in place; runs inside the transaction.
TransitionHook = Callable[[Any, TransitionContext], None]

# Guard signature: return an error string to BLOCK the transition, None to allow.
# Guards run after the transition-map check and before any mutation.
TransitionGuard = Callable[[Any, TransitionContext], Optional[str]]


@dataclass
class WorkflowSpec:
    domain: str
    entity_type: str
    model: type
    transitions: Dict[str, List[str]]
    status_attr: str = "status"
    on_enter: Dict[str, TransitionHook] = field(default_factory=dict)
    # target state -> minimum role required (viewer < operator < admin).
    # Endpoints already gate at operator; this raises the bar per state.
    role_requirements: Dict[str, str] = field(default_factory=dict)
    # target state -> guard callable; a returned string blocks with 409.
    guards: Dict[str, TransitionGuard] = field(default_factory=dict)
    # state -> max hours an entity may sit in it before it counts as an SLA
    # breach (stale). Computed on read from updated_at/created_at — no
    # background job, so the numbers are always live and testable.
    sla_hours: Dict[str, float] = field(default_factory=dict)

    @property
    def states(self) -> List[str]:
        seen: List[str] = []
        for src, targets in self.transitions.items():
            for s in [src, *targets]:
                if s not in seen:
                    seen.append(s)
        return seen

    def allowed_from(self, state: str) -> List[str]:
        return list(self.transitions.get(state, []))

    def describe(self) -> dict:
        """Serializable spec — the frontend renders action buttons from this."""
        return {
            "domain": self.domain,
            "entity_type": self.entity_type,
            "status_attr": self.status_attr,
            "states": self.states,
            "transitions": {k: list(v) for k, v in self.transitions.items()},
            "role_requirements": dict(self.role_requirements),
            "sla_hours": dict(self.sla_hours),
        }


class TransitionRequest(BaseModel):
    """Request body for every POST .../transition endpoint."""
    to_state: str = Field(..., min_length=1, max_length=64)
    note: Optional[str] = Field(None, max_length=512)


def _current_state(obj: Any, spec: WorkflowSpec) -> str:
    raw = getattr(obj, spec.status_attr)
    return raw.value if hasattr(raw, "value") else str(raw)


def _coerce_state(spec: WorkflowSpec, value: str) -> Any:
    """Convert the incoming string to the column's enum class when one exists."""
    col = spec.model.__table__.columns.get(spec.status_attr)
    enum_cls = getattr(col.type, "enum_class", None) if col is not None else None
    if enum_cls is not None:
        return enum_cls(value)
    return value


async def apply_transition(
    db: AsyncSession,
    spec: WorkflowSpec,
    entity_id: str,
    to_state: str,
    tenant: dict,
    note: Optional[str] = None,
) -> dict:
    """Perform one guarded, audited state transition. Raises HTTPException."""
    tenant_id = tenant["tenant_id"]

    if to_state not in spec.states:
        raise HTTPException(422, detail={
            "error": "unknown_state",
            "to_state": to_state,
            "known_states": spec.states,
        })

    q = await db.execute(
        select(spec.model).where(
            spec.model.id == entity_id,
            spec.model.tenant_id == tenant_id,
        )
    )
    obj = q.scalar_one_or_none()
    if not obj:
        # 404 (not 403) for another tenant's row: 403 would confirm the id exists.
        raise HTTPException(404, detail=f"{spec.entity_type} not found")

    from_state = _current_state(obj, spec)
    allowed = spec.allowed_from(from_state)
    if to_state not in allowed:
        raise HTTPException(409, detail={
            "error": "invalid_transition",
            "entity_type": spec.entity_type,
            "from_state": from_state,
            "to_state": to_state,
            "allowed": allowed,
        })

    # Per-state role floor (on top of the endpoint's operator gate).
    required_role = spec.role_requirements.get(to_state)
    if required_role:
        from app.core.tenant import ROLE_HIERARCHY
        caller_level = ROLE_HIERARCHY.get(tenant.get("role", "viewer"), 0)
        if caller_level < ROLE_HIERARCHY.get(required_role, 99):
            raise HTTPException(403, detail={
                "error": "role_required",
                "to_state": to_state,
                "required_role": required_role,
                "caller_role": tenant.get("role"),
            })

    ctx = TransitionContext(
        tenant_id=tenant_id,
        actor=tenant.get("name") or tenant.get("email"),
        actor_role=tenant.get("role"),
        note=note,
        now=datetime.now(timezone.utc),
    )

    # Business guard: blocks with the guard's reason (e.g. duplicate-flagged
    # invoice cannot be paid) even though the transition map would allow it.
    guard = spec.guards.get(to_state)
    if guard:
        reason = guard(obj, ctx)
        if reason:
            raise HTTPException(409, detail={
                "error": "guard_blocked",
                "to_state": to_state,
                "reason": reason,
            })

    setattr(obj, spec.status_attr, _coerce_state(spec, to_state))
    hook = spec.on_enter.get(to_state)
    if hook:
        hook(obj, ctx)

    event = WorkflowEvent(
        tenant_id=tenant_id,
        domain=spec.domain,
        entity_type=spec.entity_type,
        entity_id=entity_id,
        from_state=from_state,
        to_state=to_state,
        actor=ctx.actor,
        actor_role=ctx.actor_role,
        note=note,
        context={},
    )
    db.add(event)
    await db.commit()

    await record_security_event(
        tenant_id=tenant_id,
        event_type="MODIFICATION",
        action="WRITE",
        actor=ctx.actor,
        actor_role=ctx.actor_role,
        resource_type=spec.entity_type,
        resource_id=entity_id,
        details={"workflow": f"{from_state} -> {to_state}", "domain": spec.domain},
    )

    # Live UI push: every open view refreshes via useLiveRefresh on any tenant
    # WS message. Persistence already happened above (WorkflowEvent), so this
    # is broadcast-only and must never fail the request.
    try:
        from app.api.routes.ws import manager as ws_manager
        await ws_manager.broadcast_to_tenant(tenant_id, {
            "type": "workflow_transition",
            "domain": spec.domain,
            "entity_type": spec.entity_type,
            "entity_id": entity_id,
            "from_state": from_state,
            "to_state": to_state,
            "actor": ctx.actor,
        })
    except Exception:  # pragma: no cover - broadcast is best-effort
        pass

    return {
        "entity_type": spec.entity_type,
        "entity_id": entity_id,
        "from_state": from_state,
        "to_state": to_state,
        "allowed_next": spec.allowed_from(to_state),
        "at": ctx.now.isoformat(),
        "note": note,
    }


class BulkTransitionRequest(BaseModel):
    """Request body for every POST .../bulk-transition endpoint."""
    ids: List[str] = Field(..., min_length=1, max_length=200)
    to_state: str = Field(..., min_length=1, max_length=64)
    note: Optional[str] = Field(None, max_length=512)


async def apply_bulk_transition(
    db: AsyncSession,
    spec: WorkflowSpec,
    ids: List[str],
    to_state: str,
    tenant: dict,
    note: Optional[str] = None,
) -> dict:
    """Apply one transition to many entities; per-id outcomes, never all-or-
    nothing. A row that fails (illegal move, guard, missing) is reported with
    its reason while the rest proceed — bulk triage must not stop at the
    first already-resolved ticket."""
    results, succeeded = [], 0
    for entity_id in dict.fromkeys(ids):  # de-dupe, keep order
        try:
            res = await apply_transition(db, spec, entity_id, to_state, tenant, note=note)
            results.append({"id": entity_id, "ok": True,
                            "from_state": res["from_state"], "to_state": res["to_state"]})
            succeeded += 1
        except HTTPException as e:
            detail = e.detail if isinstance(e.detail, dict) else {"error": str(e.detail)}
            results.append({"id": entity_id, "ok": False,
                            "status_code": e.status_code, **detail})
    return {"entity_type": spec.entity_type, "to_state": to_state,
            "requested": len(results), "succeeded": succeeded,
            "failed": len(results) - succeeded, "results": results}


def _entity_title(obj: Any) -> str:
    for attr in ("subject", "title", "name", "invoice_number", "report_number",
                 "incident_number", "po_number", "item_description"):
        v = getattr(obj, attr, None)
        if v:
            return str(v)
    return obj.id


async def find_stale_entities(
    db: AsyncSession,
    spec: WorkflowSpec,
    tenant_id: str,
    limit: int = 100,
) -> List[dict]:
    """Entities sitting past their state's SLA, worst-first. Age is measured
    from updated_at (last touch) and falls back to created_at for models
    without an update timestamp."""
    if not spec.sla_hours:
        return []
    now = datetime.now(timezone.utc)
    q = await db.execute(
        select(spec.model).where(spec.model.tenant_id == tenant_id).limit(2000)
    )
    breaches = []
    for obj in q.scalars().all():
        state = _current_state(obj, spec)
        max_hours = spec.sla_hours.get(state)
        if max_hours is None:
            continue
        stamp = getattr(obj, "updated_at", None) or getattr(obj, "created_at", None)
        if stamp is None:
            continue
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        age_hours = (now - stamp).total_seconds() / 3600.0
        if age_hours > max_hours:
            breaches.append({
                "domain": spec.domain,
                "entity_type": spec.entity_type,
                "entity_id": obj.id,
                "title": _entity_title(obj),
                "state": state,
                "sla_hours": max_hours,
                "age_hours": round(age_hours, 1),
                "over_by_hours": round(age_hours - max_hours, 1),
            })
    breaches.sort(key=lambda b: b["over_by_hours"], reverse=True)
    return breaches[:limit]


async def list_workflow_events(
    db: AsyncSession,
    tenant_id: str,
    domain: Optional[str] = None,
    entity_type: Optional[str] = None,
    entity_id: Optional[str] = None,
    limit: int = 100,
) -> List[dict]:
    """Tenant-scoped transition history, newest first."""
    q = select(WorkflowEvent).where(WorkflowEvent.tenant_id == tenant_id)
    if domain:
        q = q.where(WorkflowEvent.domain == domain)
    if entity_type:
        q = q.where(WorkflowEvent.entity_type == entity_type)
    if entity_id:
        q = q.where(WorkflowEvent.entity_id == entity_id)
    result = await db.execute(q.order_by(WorkflowEvent.created_at.desc()).limit(min(limit, 500)))
    return [
        {
            "id": e.id,
            "domain": e.domain,
            "entity_type": e.entity_type,
            "entity_id": e.entity_id,
            "from_state": e.from_state,
            "to_state": e.to_state,
            "actor": e.actor,
            "actor_role": e.actor_role,
            "note": e.note,
            "at": str(e.created_at),
        }
        for e in result.scalars().all()
    ]
