"""
KAEOS — Workspace API (Sprints 6, 7, 9, 10)

Cross-domain collaboration surface layered on top of the workflow engine:
  - Assignment: assign/unassign any entity, "My Work", workload
  - Comments: threaded notes + @mentions on any entity
  - Notifications: unified feed with unread counts + mark-read
  - Digest: a one-call daily rollup
  - Saved segments: named per-domain filters
  - CSV export: any domain list rendered as a downloadable file
All entity references are validated against the workflow registry, so an
assignment or comment can never be pinned to a bogus entity type.
"""
import csv
import io
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.tenant import get_tenant, get_tenant_id, require_role
from app.core import collaboration as collab
from app.services.workflow_registry import get_spec

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/org", tags=["Workspace"])


async def _load_entity(db: AsyncSession, entity_type: str, entity_id: str, tenant_id: str):
    """Validate entity_type + fetch the row tenant-scoped (404 on miss)."""
    spec = get_spec(entity_type)
    if spec is None:
        raise HTTPException(404, detail=f"Unknown entity type '{entity_type}'.")
    q = await db.execute(
        select(spec.model).where(spec.model.id == entity_id,
                                 spec.model.tenant_id == tenant_id)
    )
    obj = q.scalar_one_or_none()
    if obj is None:
        raise HTTPException(404, detail=f"{entity_type} not found")
    return spec, obj


# ═══════════════════════════════════════════════════════════════════════
# Assignment  (Sprint 6)
# ═══════════════════════════════════════════════════════════════════════

class AssignRequest(BaseModel):
    assignee: str = Field(..., min_length=1, max_length=128)
    note: Optional[str] = Field(None, max_length=512)


@router.post("/entities/{entity_type}/{entity_id}/assign")
async def assign(entity_type: str, entity_id: str, body: AssignRequest,
                 tenant: dict = Depends(require_role("operator")),
                 db: AsyncSession = Depends(get_db)):
    spec, _ = await _load_entity(db, entity_type, entity_id, tenant["tenant_id"])
    return await collab.assign_entity(
        db, tenant["tenant_id"], spec.domain, entity_type, entity_id,
        body.assignee, collab.caller_identity(tenant), body.note)


@router.delete("/entities/{entity_type}/{entity_id}/assign")
async def unassign(entity_type: str, entity_id: str,
                   tenant: dict = Depends(require_role("operator")),
                   db: AsyncSession = Depends(get_db)):
    ok = await collab.unassign_entity(db, tenant["tenant_id"], entity_type, entity_id)
    if not ok:
        raise HTTPException(404, detail="No assignment to remove")
    return {"unassigned": True}


async def _hydrate_assignments(db: AsyncSession, tenant_id: str, items: list) -> list:
    """Attach each entity's current title + state so the UI renders a real row."""
    from app.core.workflow import _current_state
    out = []
    for it in items:
        spec = get_spec(it["entity_type"])
        title, state = None, None
        if spec is not None:
            q = await db.execute(
                select(spec.model).where(spec.model.id == it["entity_id"],
                                         spec.model.tenant_id == tenant_id))
            obj = q.scalar_one_or_none()
            if obj is not None:
                title = (getattr(obj, "title", None) or getattr(obj, "subject", None)
                         or getattr(obj, "name", None) or getattr(obj, "invoice_number", None)
                         or getattr(obj, "incident_number", None) or obj.id)
                state = _current_state(obj, spec)
        out.append({**it, "title": title, "state": state})
    return out


@router.get("/my-work")
async def my_work(tenant: dict = Depends(get_tenant), db: AsyncSession = Depends(get_db)):
    """Everything assigned to the caller, across all domains, hydrated with state."""
    me = collab.caller_identity(tenant)
    items = await collab.list_assignments(db, tenant["tenant_id"], assignee=me)
    return {"assignee": me, "items": await _hydrate_assignments(db, tenant["tenant_id"], items)}


@router.get("/workload")
async def workload(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    return {"workload": await collab.workload(db, tenant_id)}


@router.get("/entities/{entity_type}/{entity_id}/assignment")
async def get_assignment(entity_type: str, entity_id: str,
                         tenant_id: str = Depends(get_tenant_id),
                         db: AsyncSession = Depends(get_db)):
    return {"assignee": await collab.assignee_of(db, tenant_id, entity_type, entity_id)}


# ═══════════════════════════════════════════════════════════════════════
# Comments  (Sprint 7)
# ═══════════════════════════════════════════════════════════════════════

class CommentRequest(BaseModel):
    body: str = Field(..., min_length=1, max_length=4000)


@router.get("/entities/{entity_type}/{entity_id}/comments")
async def get_comments(entity_type: str, entity_id: str,
                       tenant_id: str = Depends(get_tenant_id),
                       db: AsyncSession = Depends(get_db)):
    return await collab.list_comments(db, tenant_id, entity_type, entity_id)


@router.post("/entities/{entity_type}/{entity_id}/comments", status_code=201)
async def add_comment(entity_type: str, entity_id: str, body: CommentRequest,
                      tenant: dict = Depends(require_role("operator")),
                      db: AsyncSession = Depends(get_db)):
    spec, _ = await _load_entity(db, entity_type, entity_id, tenant["tenant_id"])
    res = await collab.add_comment(db, tenant["tenant_id"], spec.domain, entity_type,
                                   entity_id, collab.caller_identity(tenant), body.body)
    # A comment with @mentions raises an actionable notification for each handle.
    if res["mentions"]:
        from app.models.agent_factory import ActivityEventType, ActivityFeedEvent, ActivitySeverity
        db.add(ActivityFeedEvent(
            tenant_id=tenant["tenant_id"], event_type=ActivityEventType.PROACTIVE_ALERT,
            severity=ActivitySeverity.INFO,
            title=f"You were mentioned on a {entity_type.replace('_', ' ')}",
            description=res["body"][:240], source_type=entity_type, source_id=entity_id,
            requires_action=False,
            event_metadata={"domain": spec.domain, "mentions": res["mentions"]},
        ))
        await db.commit()
    return res


@router.delete("/comments/{comment_id}")
async def delete_comment(comment_id: str,
                         tenant: dict = Depends(require_role("operator")),
                         db: AsyncSession = Depends(get_db)):
    try:
        ok = await collab.delete_comment(
            db, tenant["tenant_id"], comment_id, collab.caller_identity(tenant),
            is_admin=tenant.get("role") == "admin")
    except PermissionError as e:
        raise HTTPException(403, detail=str(e))
    if not ok:
        raise HTTPException(404, detail="Comment not found")
    return {"deleted": True}


# ═══════════════════════════════════════════════════════════════════════
# Notifications  (Sprint 9)
# ═══════════════════════════════════════════════════════════════════════

def _serialize_notification(e) -> dict:
    return {
        "id": e.id,
        "type": e.event_type.value if hasattr(e.event_type, "value") else str(e.event_type),
        "severity": e.severity.value if hasattr(e.severity, "value") else str(e.severity),
        "title": e.title, "description": e.description,
        "source_type": e.source_type, "source_id": e.source_id,
        "is_read": bool(e.is_read), "requires_action": bool(e.requires_action),
        "action_taken": bool(e.action_taken),
        "at": str(e.created_at) if e.created_at else None,
    }


async def _notification_counts(db: AsyncSession, tenant_id: str) -> dict:
    from sqlalchemy import func as sqlfunc
    from app.models.agent_factory import ActivityFeedEvent
    unread = (await db.execute(
        select(sqlfunc.count()).select_from(ActivityFeedEvent).where(
            ActivityFeedEvent.tenant_id == tenant_id,
            ActivityFeedEvent.is_read == False))).scalar() or 0  # noqa: E712
    action = (await db.execute(
        select(sqlfunc.count()).select_from(ActivityFeedEvent).where(
            ActivityFeedEvent.tenant_id == tenant_id,
            ActivityFeedEvent.requires_action == True,           # noqa: E712
            ActivityFeedEvent.action_taken == False))).scalar() or 0  # noqa: E712
    return {"unread": int(unread), "action_required": int(action)}


@router.get("/notifications")
async def notifications(unread_only: bool = False, limit: int = 50,
                        tenant_id: str = Depends(get_tenant_id),
                        db: AsyncSession = Depends(get_db)):
    """Unified notification feed on the request session (one DB, one tenant)."""
    from app.models.agent_factory import ActivityFeedEvent
    q = select(ActivityFeedEvent).where(ActivityFeedEvent.tenant_id == tenant_id)
    if unread_only:
        q = q.where(ActivityFeedEvent.is_read == False)  # noqa: E712
    result = await db.execute(q.order_by(ActivityFeedEvent.created_at.desc()).limit(min(limit, 200)))
    items = [_serialize_notification(e) for e in result.scalars().all()]
    return {"counts": await _notification_counts(db, tenant_id), "items": items}


class MarkReadRequest(BaseModel):
    ids: list[str] = Field(default_factory=list)


@router.post("/notifications/read")
async def mark_read(body: MarkReadRequest, tenant_id: str = Depends(get_tenant_id),
                    db: AsyncSession = Depends(get_db)):
    from sqlalchemy import update
    from app.models.agent_factory import ActivityFeedEvent
    stmt = update(ActivityFeedEvent).where(
        ActivityFeedEvent.tenant_id == tenant_id,
        ActivityFeedEvent.id.in_(body.ids or [])).values(is_read=True)
    res = await db.execute(stmt)
    await db.commit()
    return {"marked": res.rowcount}


@router.post("/notifications/{event_id}/resolve")
async def resolve_notification(event_id: str,
                               tenant: dict = Depends(require_role("operator")),
                               db: AsyncSession = Depends(get_db)):
    from datetime import datetime, timezone
    from sqlalchemy import update
    from app.models.agent_factory import ActivityFeedEvent
    stmt = update(ActivityFeedEvent).where(
        ActivityFeedEvent.tenant_id == tenant["tenant_id"],
        ActivityFeedEvent.id == event_id).values(
        action_taken=True, action_taken_by=collab.caller_identity(tenant),
        action_taken_at=datetime.now(timezone.utc), is_read=True)
    res = await db.execute(stmt)
    await db.commit()
    if not res.rowcount:
        raise HTTPException(404, detail="Notification not found")
    return {"resolved": True}


@router.get("/digest")
async def digest(tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    """A one-call rollup: pulse health snapshot + workload + open notifications."""
    from app.api.routes.org_pulse import org_pulse
    from app.models.agent_factory import ActivityFeedEvent

    pulse = await org_pulse(tenant_id=tenant_id, db=db)
    action_q = await db.execute(
        select(ActivityFeedEvent).where(
            ActivityFeedEvent.tenant_id == tenant_id,
            ActivityFeedEvent.requires_action == True,   # noqa: E712
            ActivityFeedEvent.action_taken == False)     # noqa: E712
        .order_by(ActivityFeedEvent.created_at.desc()).limit(10))
    action_items = [_serialize_notification(e) for e in action_q.scalars().all()]
    load = await collab.workload(db, tenant_id)
    return {
        "org_health": pulse["org_health"],
        "domains": [{"domain": d["domain"], "health": d["health"]} for d in pulse["domains"]],
        "top_insights": pulse["insights"][:5],
        "notifications": await _notification_counts(db, tenant_id),
        "action_required": action_items,
        "workload": load,
    }


# ═══════════════════════════════════════════════════════════════════════
# Saved segments  (Sprint 10)
# ═══════════════════════════════════════════════════════════════════════

class SegmentRequest(BaseModel):
    domain: str = Field(..., min_length=1, max_length=32)
    name: str = Field(..., min_length=1, max_length=128)
    entity_type: Optional[str] = None
    definition: dict = Field(default_factory=dict)


@router.get("/segments")
async def get_segments(domain: Optional[str] = None,
                       tenant_id: str = Depends(get_tenant_id),
                       db: AsyncSession = Depends(get_db)):
    return await collab.list_segments(db, tenant_id, domain=domain)


@router.post("/segments", status_code=201)
async def create_segment(body: SegmentRequest,
                         tenant: dict = Depends(require_role("operator")),
                         db: AsyncSession = Depends(get_db)):
    if body.entity_type and get_spec(body.entity_type) is None:
        raise HTTPException(422, detail=f"Unknown entity type '{body.entity_type}'.")
    return await collab.save_segment(db, tenant["tenant_id"], body.domain, body.name,
                                     body.definition, body.entity_type,
                                     collab.caller_identity(tenant))


@router.delete("/segments/{segment_id}")
async def remove_segment(segment_id: str,
                         tenant: dict = Depends(require_role("operator")),
                         db: AsyncSession = Depends(get_db)):
    if not await collab.delete_segment(db, tenant["tenant_id"], segment_id):
        raise HTTPException(404, detail="Segment not found")
    return {"deleted": True}


# ═══════════════════════════════════════════════════════════════════════
# CSV export  (Sprint 10)
# ═══════════════════════════════════════════════════════════════════════

@router.get("/export/{entity_type}.csv")
async def export_csv(entity_type: str, tenant_id: str = Depends(get_tenant_id),
                     db: AsyncSession = Depends(get_db)):
    """Stream a tenant-scoped CSV of every row of one workflow entity type."""
    spec = get_spec(entity_type)
    if spec is None:
        raise HTTPException(404, detail=f"Unknown entity type '{entity_type}'.")

    q = await db.execute(
        select(spec.model).where(spec.model.tenant_id == tenant_id).limit(10000)
    )
    rows = q.scalars().all()

    # Export a stable, human-useful column set: every simple scalar column.
    cols = [c.name for c in spec.model.__table__.columns
            if c.name not in ("tenant_id",)]

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(cols)
    for obj in rows:
        out = []
        for c in cols:
            v = getattr(obj, c, None)
            out.append(v.value if hasattr(v, "value") else ("" if v is None else str(v)))
        writer.writerow(out)
    buf.seek(0)

    return StreamingResponse(
        iter([buf.getvalue()]), media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{entity_type}.csv"'})
