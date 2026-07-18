"""KAEOS — Enterprise Calendar Models (AEOS P4 — Temporal Reasoning)
Time-aware cognition: fiscal calendars, payroll cycles, compliance deadlines.
"""
from sqlalchemy import (
    Column, String, Float, DateTime, ForeignKey,
    Text, JSON, Enum, Boolean,
)
from sqlalchemy.sql import func
import uuid
import enum

from app.models.domain import Base


def _uuid():
    return str(uuid.uuid4())


class CalendarEventType(str, enum.Enum):
    FISCAL_YEAR = "FISCAL_YEAR"
    PAYROLL_CYCLE = "PAYROLL_CYCLE"
    COMPLIANCE_DEADLINE = "COMPLIANCE_DEADLINE"
    RELEASE_FREEZE = "RELEASE_FREEZE"
    OPEN_ENROLLMENT = "OPEN_ENROLLMENT"
    AUDIT_WINDOW = "AUDIT_WINDOW"
    BUDGET_CYCLE = "BUDGET_CYCLE"
    CUSTOM = "CUSTOM"


class EnterpriseCalendar(Base):
    """Enterprise calendar events that influence agent decision priority.
    
    When an action falls within a calendar window, its OODA priority
    is boosted by priority_boost_pct (default 40%). This enables
    deadline-aware agent behavior.
    """
    __tablename__ = 'enterprise_calendar'

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)

    # Event identity
    calendar_type = Column(Enum(CalendarEventType), nullable=False, index=True)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)

    # Time window
    start_date = Column(DateTime(timezone=True), nullable=False)
    end_date = Column(DateTime(timezone=True), nullable=False)

    # Recurrence (iCal RRULE format, null = one-time)
    # Example: "FREQ=YEARLY;BYMONTH=1;BYMONTHDAY=1" for annual Jan 1
    recurrence_rule = Column(String, nullable=True)

    # Scope
    department = Column(String(64), nullable=True, index=True)  # null = org-wide
    applies_to_domains = Column(JSON, default=list)  # Filter to specific domains

    # Priority impact
    priority_boost_pct = Column(Float, default=40.0)  # % boost when within window
    is_blocking = Column(Boolean, default=False)  # If true, blocks agent execution entirely (e.g., release freeze)

    # State
    is_active = Column(Boolean, default=True, index=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class TemporalAnomalyLog(Base):
    """Records temporal anomalies detected by the Temporal Reasoning Engine.
    
    Fires when a signal arrives outside its expected time window
    (e.g., payroll event on non-payroll day, config change during release freeze).
    """
    __tablename__ = 'temporal_anomaly_logs'

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)

    # What was anomalous
    signal_id = Column(String, ForeignKey('signals.id'), nullable=True)
    anomaly_type = Column(String(32))  # OUT_OF_WINDOW, UNEXPECTED_TIMING, FREEZE_VIOLATION

    # Calendar context
    calendar_event_id = Column(String, ForeignKey('enterprise_calendar.id'), nullable=True)
    expected_window = Column(String)  # Human-readable: "Expected during payroll cycle (15th-20th)"
    actual_timestamp = Column(DateTime(timezone=True), nullable=False)

    # Impact
    severity = Column(String(16), default="WARNING")  # INFO, WARNING, CRITICAL
    was_escalated = Column(Boolean, default=False)
    description = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
