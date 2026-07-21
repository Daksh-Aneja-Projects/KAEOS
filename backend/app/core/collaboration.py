"""
KAEOS Core — Collaboration Layer (Sprints 6, 7, 10)

Side-tables keyed by (tenant, entity_type, entity_id) that hang off any
workflow entity without touching the heterogeneous domain models:

  - WorkflowAssignment : who owns an entity  -> "My Work" + workload
  - WorkflowComment     : threaded notes + @mentions
  - SavedSegment        : a named, per-domain filter the UI can recall

Everything is tenant-scoped and identity-keyed by the caller's email or name.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import Column, DateTime, JSON, String, Text, select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import func

from app.models.domain import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def caller_identity(tenant: dict) -> str:
    """Canonical actor string for a request — email preferred, name fallback."""
    return tenant.get("email") or tenant.get("name") or "unknown"


_MENTION_RE = re.compile(r"@([A-Za-z0-9._%+-]+(?:@[A-Za-z0-9.-]+\.[A-Za-z]{2,})?)")


def extract_mentions(text: str) -> List[str]:
    """@handles referenced in a comment body (email or bare handle)."""
    return list(dict.fromkeys(_MENTION_RE.findall(text or "")))


# ══════════════════════════════════════════════════════════════════════════
# Models
# ══════════════════════════════════════════════════════════════════════════

class WorkflowAssignment(Base):
    """Current owner of one workflow entity (one row per entity — upserted)."""
    __tablename__ = "core_workflow_assignments"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)

    domain = Column(String(32), nullable=False, index=True)
    entity_type = Column(String(64), nullable=False, index=True)
    entity_id = Column(String, nullable=False, index=True)

    assignee = Column(String(128), nullable=False, index=True)
    assigned_by = Column(String(128), nullable=True)
    note = Column(String(512), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class WorkflowComment(Base):
    """A note on a workflow entity. Flat thread ordered by time."""
    __tablename__ = "core_workflow_comments"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)

    domain = Column(String(32), nullable=False, index=True)
    entity_type = Column(String(64), nullable=False, index=True)
    entity_id = Column(String, nullable=False, index=True)

    author = Column(String(128), nullable=False)
    body = Column(Text, nullable=False)
    mentions = Column(JSON, default=list)

    created_at = Column(DateTime(timezone=True), server_default=func.now())


class SavedSegment(Base):
    """A named, per-domain filter definition the frontend recalls as a chip."""
    __tablename__ = "core_saved_segments"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)

    domain = Column(String(32), nullable=False, index=True)
    name = Column(String(128), nullable=False)
    entity_type = Column(String(64), nullable=True)
    # Arbitrary filter payload the frontend interprets: {status, assignee, ...}
    definition = Column(JSON, default=dict)
    created_by = Column(String(128), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())


# ══════════════════════════════════════════════════════════════════════════
# Assignment helpers
# ══════════════════════════════════════════════════════════════════════════

async def assign_entity(
    db: AsyncSession, tenant_id: str, domain: str, entity_type: str,
    entity_id: str, assignee: str, assigned_by: str, note: Optional[str] = None,
) -> dict:
    """Upsert the owner of an entity (one assignment per entity)."""
    q = await db.execute(
        select(WorkflowAssignment).where(
            WorkflowAssignment.tenant_id == tenant_id,
            WorkflowAssignment.entity_type == entity_type,
            WorkflowAssignment.entity_id == entity_id,
        )
    )
    row = q.scalar_one_or_none()
    if row is None:
        row = WorkflowAssignment(
            tenant_id=tenant_id, domain=domain, entity_type=entity_type,
            entity_id=entity_id, assignee=assignee, assigned_by=assigned_by, note=note,
        )
        db.add(row)
    else:
        row.assignee = assignee
        row.assigned_by = assigned_by
        row.note = note
    await db.commit()
    await db.refresh(row)
    return {"entity_type": entity_type, "entity_id": entity_id,
            "assignee": row.assignee, "assigned_by": row.assigned_by}


async def unassign_entity(
    db: AsyncSession, tenant_id: str, entity_type: str, entity_id: str,
) -> bool:
    q = await db.execute(
        select(WorkflowAssignment).where(
            WorkflowAssignment.tenant_id == tenant_id,
            WorkflowAssignment.entity_type == entity_type,
            WorkflowAssignment.entity_id == entity_id,
        )
    )
    row = q.scalar_one_or_none()
    if row is None:
        return False
    await db.delete(row)
    await db.commit()
    return True


async def list_assignments(
    db: AsyncSession, tenant_id: str, assignee: Optional[str] = None,
    domain: Optional[str] = None, limit: int = 500,
) -> List[dict]:
    q = select(WorkflowAssignment).where(WorkflowAssignment.tenant_id == tenant_id)
    if assignee:
        q = q.where(WorkflowAssignment.assignee == assignee)
    if domain:
        q = q.where(WorkflowAssignment.domain == domain)
    result = await db.execute(q.order_by(WorkflowAssignment.updated_at.desc()).limit(limit))
    return [
        {"domain": a.domain, "entity_type": a.entity_type, "entity_id": a.entity_id,
         "assignee": a.assignee, "assigned_by": a.assigned_by, "note": a.note,
         "at": str(a.updated_at)}
        for a in result.scalars().all()
    ]


async def assignee_of(db: AsyncSession, tenant_id: str, entity_type: str,
                      entity_id: str) -> Optional[str]:
    q = await db.execute(
        select(WorkflowAssignment.assignee).where(
            WorkflowAssignment.tenant_id == tenant_id,
            WorkflowAssignment.entity_type == entity_type,
            WorkflowAssignment.entity_id == entity_id,
        )
    )
    return q.scalar_one_or_none()


async def workload(db: AsyncSession, tenant_id: str) -> List[dict]:
    """Open-assignment counts per assignee, busiest first."""
    q = await db.execute(
        select(WorkflowAssignment.assignee, func.count())
        .where(WorkflowAssignment.tenant_id == tenant_id)
        .group_by(WorkflowAssignment.assignee)
        .order_by(func.count().desc())
    )
    return [{"assignee": a, "count": int(c)} for a, c in q.all()]


# ══════════════════════════════════════════════════════════════════════════
# Comment helpers
# ══════════════════════════════════════════════════════════════════════════

async def add_comment(
    db: AsyncSession, tenant_id: str, domain: str, entity_type: str,
    entity_id: str, author: str, body: str,
) -> dict:
    mentions = extract_mentions(body)
    row = WorkflowComment(
        tenant_id=tenant_id, domain=domain, entity_type=entity_type,
        entity_id=entity_id, author=author, body=body, mentions=mentions,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return {"id": row.id, "author": row.author, "body": row.body,
            "mentions": mentions, "at": str(row.created_at)}


async def list_comments(
    db: AsyncSession, tenant_id: str, entity_type: str, entity_id: str,
    limit: int = 200,
) -> List[dict]:
    q = await db.execute(
        select(WorkflowComment).where(
            WorkflowComment.tenant_id == tenant_id,
            WorkflowComment.entity_type == entity_type,
            WorkflowComment.entity_id == entity_id,
        ).order_by(WorkflowComment.created_at.asc()).limit(limit)
    )
    return [
        {"id": c.id, "author": c.author, "body": c.body,
         "mentions": c.mentions or [], "at": str(c.created_at)}
        for c in q.scalars().all()
    ]


async def delete_comment(db: AsyncSession, tenant_id: str, comment_id: str,
                         author: str, is_admin: bool) -> bool:
    """Author (or an admin) may delete a comment."""
    q = await db.execute(
        select(WorkflowComment).where(
            WorkflowComment.tenant_id == tenant_id,
            WorkflowComment.id == comment_id,
        )
    )
    row = q.scalar_one_or_none()
    if row is None:
        return False
    if row.author != author and not is_admin:
        raise PermissionError("Only the author or an admin can delete this comment.")
    await db.delete(row)
    await db.commit()
    return True


# ══════════════════════════════════════════════════════════════════════════
# Saved-segment helpers
# ══════════════════════════════════════════════════════════════════════════

async def save_segment(
    db: AsyncSession, tenant_id: str, domain: str, name: str,
    definition: dict, entity_type: Optional[str], created_by: str,
) -> dict:
    row = SavedSegment(
        tenant_id=tenant_id, domain=domain, name=name,
        entity_type=entity_type, definition=definition or {}, created_by=created_by,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return {"id": row.id, "domain": row.domain, "name": row.name,
            "entity_type": row.entity_type, "definition": row.definition}


async def list_segments(db: AsyncSession, tenant_id: str,
                        domain: Optional[str] = None) -> List[dict]:
    q = select(SavedSegment).where(SavedSegment.tenant_id == tenant_id)
    if domain:
        q = q.where(SavedSegment.domain == domain)
    result = await db.execute(q.order_by(SavedSegment.created_at.desc()).limit(200))
    return [
        {"id": s.id, "domain": s.domain, "name": s.name,
         "entity_type": s.entity_type, "definition": s.definition or {},
         "created_by": s.created_by}
        for s in result.scalars().all()
    ]


async def delete_segment(db: AsyncSession, tenant_id: str, segment_id: str) -> bool:
    q = await db.execute(
        select(SavedSegment).where(
            SavedSegment.tenant_id == tenant_id, SavedSegment.id == segment_id,
        )
    )
    row = q.scalar_one_or_none()
    if row is None:
        return False
    await db.delete(row)
    await db.commit()
    return True
