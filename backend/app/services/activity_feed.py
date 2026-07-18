"""KAEOS — Activity Feed Service
Platform-wide real-time event bus replacing static dashboards.
"""
import logging
from typing import Optional
from datetime import datetime, timezone

from sqlalchemy import select, update, desc

from app.core.database import AsyncSessionLocal
from app.models.agent_factory import (
    ActivityFeedEvent, ActivityEventType, ActivitySeverity
)

logger = logging.getLogger(__name__)


class ActivityFeedService:
    """Emits and queries platform-wide activity events.
    
    Every significant platform action (agent start/stop, HITL request,
    decay alert, conflict detection, blueprint creation) emits an event
    into this feed. The Command Center renders these in real-time.
    """

    async def emit(
        self,
        event_type: ActivityEventType,
        title: str,
        tenant_id: str,
        description: Optional[str] = None,
        metadata: Optional[dict] = None,
        source_type: Optional[str] = None,
        source_id: Optional[str] = None,
        severity: ActivitySeverity = ActivitySeverity.INFO,
        requires_action: bool = False,
    ) -> ActivityFeedEvent:
        """Emit a new activity feed event."""
        event = ActivityFeedEvent(
            tenant_id=tenant_id,
            event_type=event_type,
            severity=severity,
            title=title,
            description=description,
            event_metadata=metadata or {},
            source_type=source_type,
            source_id=source_id,
            requires_action=requires_action,
        )

        async with AsyncSessionLocal() as session:
            session.add(event)
            await session.commit()
            await session.refresh(event)
            logger.info(f"[ActivityFeed] {severity.value}: {title} ({event_type.value})")
            
            # Broadcast via WebSocket
            try:
                from app.api.routes.ws import manager
                await manager.broadcast_to_tenant(tenant_id, {
                    "type": "new_event",
                    "event": self._serialize_event(event)
                })
            except Exception as e:
                logger.error(f"Failed to broadcast websocket event: {e}")
                
            return event

    async def get_feed(
        self,
        tenant_id: str,
        limit: int = 50,
        unread_only: bool = False,
        severity_filter: Optional[str] = None,
        event_type_filter: Optional[str] = None,
    ) -> list[dict]:
        """Get activity feed events for a tenant."""
        async with AsyncSessionLocal() as session:
            query = select(ActivityFeedEvent).where(
                ActivityFeedEvent.tenant_id == tenant_id
            ).order_by(desc(ActivityFeedEvent.created_at)).limit(limit)

            if unread_only:
                query = query.where(ActivityFeedEvent.is_read == False)  # noqa: E712
            if severity_filter:
                query = query.where(ActivityFeedEvent.severity == severity_filter)
            if event_type_filter:
                query = query.where(ActivityFeedEvent.event_type == event_type_filter)

            result = await session.execute(query)
            events = result.scalars().all()

            return [self._serialize_event(e) for e in events]

    async def get_action_required(self, tenant_id: str) -> list[dict]:
        """Get events that require user action (unresolved HITL, blocks, etc.)."""
        async with AsyncSessionLocal() as session:
            query = select(ActivityFeedEvent).where(
                ActivityFeedEvent.tenant_id == tenant_id,
                ActivityFeedEvent.requires_action == True,  # noqa: E712
                ActivityFeedEvent.action_taken == False,  # noqa: E712
            ).order_by(desc(ActivityFeedEvent.created_at))

            result = await session.execute(query)
            events = result.scalars().all()

            return [self._serialize_event(e) for e in events]

    async def mark_read(self, event_ids: list[str], tenant_id: str) -> int:
        """Mark events as read. Returns count of updated events."""
        async with AsyncSessionLocal() as session:
            stmt = (
                update(ActivityFeedEvent)
                .where(
                    ActivityFeedEvent.id.in_(event_ids),
                    ActivityFeedEvent.tenant_id == tenant_id,
                )
                .values(is_read=True)
            )
            result = await session.execute(stmt)
            await session.commit()
            return result.rowcount

    async def mark_action_taken(
        self,
        event_id: str,
        tenant_id: str,
        action_by: Optional[str] = None,
    ) -> None:
        """Mark an action-required event as resolved."""
        async with AsyncSessionLocal() as session:
            stmt = (
                update(ActivityFeedEvent)
                .where(
                    ActivityFeedEvent.id == event_id,
                    ActivityFeedEvent.tenant_id == tenant_id,
                )
                .values(
                    action_taken=True,
                    action_taken_by=action_by,
                    action_taken_at=datetime.now(timezone.utc),
                )
            )
            await session.execute(stmt)
            await session.commit()

    async def get_unread_count(self, tenant_id: str) -> dict:
        """Get count of unread and action-required events."""
        async with AsyncSessionLocal() as session:
            # Unread count
            unread_query = select(ActivityFeedEvent).where(
                ActivityFeedEvent.tenant_id == tenant_id,
                ActivityFeedEvent.is_read == False,  # noqa: E712
            )
            unread_result = await session.execute(unread_query)
            unread = len(unread_result.scalars().all())

            # Action required count
            action_query = select(ActivityFeedEvent).where(
                ActivityFeedEvent.tenant_id == tenant_id,
                ActivityFeedEvent.requires_action == True,  # noqa: E712
                ActivityFeedEvent.action_taken == False,  # noqa: E712
            )
            action_result = await session.execute(action_query)
            action_count = len(action_result.scalars().all())

            return {
                "unread": unread,
                "action_required": action_count,
            }

    def _serialize_event(self, event: ActivityFeedEvent) -> dict:
        """Serialize an ActivityFeedEvent to a dict."""
        return {
            "id": event.id,
            "event_type": event.event_type.value if event.event_type else None,
            "severity": event.severity.value if event.severity else None,
            "title": event.title,
            "description": event.description,
            "metadata": event.event_metadata,
            "source_type": event.source_type,
            "source_id": event.source_id,
            "is_read": event.is_read,
            "requires_action": event.requires_action,
            "action_taken": event.action_taken,
            "created_at": event.created_at.isoformat() if event.created_at else None,
        }
