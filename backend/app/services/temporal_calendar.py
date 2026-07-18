"""KAEOS — Temporal Calendar & Reasoning Engine (AEOS P4)
Enterprise calendar awareness: deadlines, seasonality, anomaly detection.
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select
from app.core.database import AsyncSessionLocal
from app.models.calendar import EnterpriseCalendar, CalendarEventType, TemporalAnomalyLog
from app.models.domain import Signal

logger = logging.getLogger(__name__)


class TemporalReasoningEngine:
    """Time-aware cognition for agent decision-making.
    
    Provides:
    - Deadline proximity scoring (boosts OODA priority within windows)
    - Temporal anomaly detection (signals outside expected windows)
    - Seasonality context for blueprint generation
    """

    async def get_deadline_proximity_score(
        self, action_domain: str, tenant_id: str, department: Optional[str] = None
    ) -> dict:
        """Calculate priority multiplier based on active calendar windows.
        
        Returns: { multiplier: float, active_events: [...], context: str }
        """
        now = datetime.now(timezone.utc)
        window_end = now + timedelta(days=30)

        async with AsyncSessionLocal() as session:
            query = select(EnterpriseCalendar).where(
                EnterpriseCalendar.tenant_id == tenant_id,
                EnterpriseCalendar.is_active == True,  # noqa: E712
                EnterpriseCalendar.start_date <= window_end,
                EnterpriseCalendar.end_date >= now,
            )

            if department:
                query = query.where(
                    (EnterpriseCalendar.department == department) |
                    (EnterpriseCalendar.department == None)  # noqa: E711
                )

            result = await session.execute(query)
            events = result.scalars().all()

        if not events:
            return {"multiplier": 1.0, "active_events": [], "context": "No active calendar events"}

        # Calculate composite multiplier from overlapping events
        max_boost = 0.0
        active = []
        blocking = False

        for event in events:
            # Check if we're inside the event window
            if event.start_date <= now <= event.end_date:
                boost = (event.priority_boost_pct or 40.0) / 100.0
                max_boost = max(max_boost, boost)
                if event.is_blocking:
                    blocking = True
                active.append({
                    "id": event.id,
                    "name": event.name,
                    "type": event.calendar_type.value if event.calendar_type else "CUSTOM",
                    "ends_at": event.end_date.isoformat() if event.end_date else None,
                    "boost_pct": event.priority_boost_pct,
                    "is_blocking": event.is_blocking,
                })
            else:
                # Approaching — within 30 days
                days_until = (event.start_date - now).days
                approach_boost = ((30 - days_until) / 30) * ((event.priority_boost_pct or 40) / 100.0)
                max_boost = max(max_boost, approach_boost * 0.5)  # Half boost for approaching
                active.append({
                    "id": event.id,
                    "name": event.name,
                    "type": event.calendar_type.value if event.calendar_type else "CUSTOM",
                    "starts_in_days": days_until,
                    "boost_pct": event.priority_boost_pct,
                    "is_blocking": event.is_blocking,
                })

        multiplier = 1.0 + max_boost
        context_parts = [f"{e['name']} ({e['type']})" for e in active[:3]]
        context = f"Active: {', '.join(context_parts)}"
        if blocking:
            context += " ⚠️ BLOCKING EVENT ACTIVE"

        return {
            "multiplier": multiplier,
            "active_events": active,
            "context": context,
            "is_blocking": blocking,
        }

    async def detect_temporal_anomaly(
        self, signal: Signal, tenant_id: str
    ) -> Optional[dict]:
        """Check if a signal arrived outside its expected time window.
        
        Returns anomaly dict if detected, None if normal.
        """
        now = datetime.now(timezone.utc)

        async with AsyncSessionLocal() as session:
            # Check for blocking events (e.g., release freeze)
            blocking_query = select(EnterpriseCalendar).where(
                EnterpriseCalendar.tenant_id == tenant_id,
                EnterpriseCalendar.is_active == True,  # noqa: E712
                EnterpriseCalendar.is_blocking == True,  # noqa: E712
                EnterpriseCalendar.start_date <= now,
                EnterpriseCalendar.end_date >= now,
            )
            result = await session.execute(blocking_query)
            blocking_events = result.scalars().all()

            if blocking_events:
                event = blocking_events[0]
                anomaly = TemporalAnomalyLog(
                    tenant_id=tenant_id,
                    signal_id=signal.id if signal else None,
                    anomaly_type="FREEZE_VIOLATION",
                    calendar_event_id=event.id,
                    expected_window=f"No activity expected during {event.name} ({event.start_date} to {event.end_date})",
                    actual_timestamp=now,
                    severity="CRITICAL",
                    description=f"Signal received during blocking event '{event.name}'. Type: {signal.signal_type if signal else 'unknown'}",
                )
                session.add(anomaly)
                await session.commit()
                await session.refresh(anomaly)

                logger.warning(f"[Temporal] ANOMALY: freeze violation during '{event.name}'")
                return {
                    "anomaly_type": "FREEZE_VIOLATION",
                    "severity": "CRITICAL",
                    "calendar_event": event.name,
                    "description": anomaly.description,
                    "anomaly_id": anomaly.id,
                }

        return None

    async def get_seasonality_context(self, department: str, tenant_id: str) -> dict:
        """Get current seasonal context for a department.
        
        Used by BlueprintGenerator to add temporal awareness to agent DAGs.
        """
        now = datetime.now(timezone.utc)

        async with AsyncSessionLocal() as session:
            query = select(EnterpriseCalendar).where(
                EnterpriseCalendar.tenant_id == tenant_id,
                EnterpriseCalendar.is_active == True,  # noqa: E712
                EnterpriseCalendar.start_date <= now,
                EnterpriseCalendar.end_date >= now,
                (EnterpriseCalendar.department == department) |
                (EnterpriseCalendar.department == None),  # noqa: E711
            )
            result = await session.execute(query)
            active = result.scalars().all()

        current_month = now.strftime("%B")
        current_quarter = f"Q{(now.month - 1) // 3 + 1}"

        context = {
            "current_month": current_month,
            "current_quarter": current_quarter,
            "day_of_week": now.strftime("%A"),
            "active_calendar_events": [
                {"name": e.name, "type": e.calendar_type.value if e.calendar_type else "CUSTOM", "ends_at": e.end_date.isoformat() if e.end_date else None}
                for e in active
            ],
            "is_month_end": now.day >= 25,
            "is_quarter_end": now.month in [3, 6, 9, 12] and now.day >= 15,
            "is_year_end": now.month == 12 and now.day >= 15,
        }
        return context

    # ─── CRUD for Calendar Events ───

    async def create_event(self, tenant_id: str, data: dict) -> dict:
        event = EnterpriseCalendar(
            tenant_id=tenant_id,
            calendar_type=data.get("calendar_type", CalendarEventType.CUSTOM),
            name=data["name"],
            description=data.get("description"),
            start_date=data["start_date"],
            end_date=data["end_date"],
            recurrence_rule=data.get("recurrence_rule"),
            department=data.get("department"),
            priority_boost_pct=data.get("priority_boost_pct", 40.0),
            is_blocking=data.get("is_blocking", False),
        )
        async with AsyncSessionLocal() as session:
            session.add(event)
            await session.commit()
            await session.refresh(event)
        return self._serialize(event)

    async def list_events(self, tenant_id: str) -> list:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(EnterpriseCalendar).where(EnterpriseCalendar.tenant_id == tenant_id).order_by(EnterpriseCalendar.start_date)
            )
            return [self._serialize(e) for e in result.scalars().all()]

    async def delete_event(self, event_id: str, tenant_id: str) -> bool:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(EnterpriseCalendar).where(EnterpriseCalendar.id == event_id, EnterpriseCalendar.tenant_id == tenant_id)
            )
            event = result.scalar_one_or_none()
            if event:
                await session.delete(event)
                await session.commit()
                return True
            return False

    def _serialize(self, e: EnterpriseCalendar) -> dict:
        return {
            "id": e.id, "name": e.name, "description": e.description,
            "calendar_type": e.calendar_type.value if e.calendar_type else None,
            "start_date": e.start_date.isoformat() if e.start_date else None,
            "end_date": e.end_date.isoformat() if e.end_date else None,
            "recurrence_rule": e.recurrence_rule, "department": e.department,
            "priority_boost_pct": e.priority_boost_pct, "is_blocking": e.is_blocking,
            "is_active": e.is_active,
        }
