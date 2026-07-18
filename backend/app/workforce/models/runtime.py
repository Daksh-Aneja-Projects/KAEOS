"""
KAEOS Workforce Layer — Runtime Models

Tracks metrics and execution state for departments and processes.
These tables grow rapidly and are used to power the analytics dashboards
and ROI calculations.
"""
from sqlalchemy import (
    Column, String, Integer, Float, DateTime, Text, JSON,
    Enum, ForeignKey, UniqueConstraint, Index,
)
from sqlalchemy.sql import func
import uuid
import enum

from app.models.domain import Base


def _uuid():
    return str(uuid.uuid4())


class MetricPeriod(str, enum.Enum):
    HOURLY = "HOURLY"
    DAILY = "DAILY"
    WEEKLY = "WEEKLY"
    MONTHLY = "MONTHLY"
    YEARLY = "YEARLY"


class ProcessExecutionStatus(str, enum.Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    WAITING_ON_HUMAN = "WAITING_ON_HUMAN"
    WAITING_ON_SYSTEM = "WAITING_ON_SYSTEM"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    ESCALATED = "ESCALATED"
    CANCELED = "CANCELED"


class WorkforceMetrics(Base):
    """
    Time-series metrics per department.

    Aggregates operational data (tasks, hours saved, cost savings) over
    specific time periods. This powers the ROI and health dashboards without
    needing to query millions of individual task records.
    """
    __tablename__ = "workforce_metrics"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    department_id = Column(String, ForeignKey("departments.id"), nullable=False, index=True)

    # Time period
    period = Column(Enum(MetricPeriod), default=MetricPeriod.DAILY)
    period_start = Column(DateTime(timezone=True), nullable=False, index=True)
    period_end = Column(DateTime(timezone=True), nullable=False)

    # Throughput
    tasks_started = Column(Integer, default=0)
    tasks_completed = Column(Integer, default=0)
    tasks_failed = Column(Integer, default=0)
    tasks_escalated = Column(Integer, default=0)             # Tasks passed to humans

    # ROI Estimates
    hours_saved_estimate = Column(Float, default=0.0)        # E.g., 2.5 hours
    cost_savings_estimate = Column(Float, default=0.0)       # E.g., $150.00

    # Operational Health
    automation_coverage_pct = Column(Float, default=0.0)     # % of work handled by agents vs humans
    human_escalation_rate = Column(Float, default=0.0)       # tasks_escalated / tasks_started
    compliance_health_pct = Column(Float, default=1.0)       # 1.0 = perfect compliance
    knowledge_coverage_pct = Column(Float, default=0.0)      # % of questions answered without escalation

    # Performance
    avg_response_time_ms = Column(Integer, default=0)        # Agent response latency
    avg_process_duration_ms = Column(Integer, default=0)     # End-to-end process duration
    agent_utilization_pct = Column(Float, default=0.0)       # % of time agents are actively working

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("tenant_id", "department_id", "period", "period_start", name="uq_metrics_period"),
        Index("ix_workforce_metrics_period", "tenant_id", "department_id", "period", "period_start"),
    )


class ProcessExecution(Base):
    """
    Tracks an individual run of a business process.

    When the ProcessEngine starts executing a BusinessProcess DAG, it creates
    this record to track state, progress, and context. If it hits a human
    checkpoint, it pauses in WAITING_ON_HUMAN state.
    """
    __tablename__ = "process_executions"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    process_id = Column(String, ForeignKey("business_processes.id"), nullable=False, index=True)
    department_id = Column(String, ForeignKey("departments.id"), nullable=False, index=True)

    # State
    status = Column(Enum(ProcessExecutionStatus), default=ProcessExecutionStatus.QUEUED)
    current_step = Column(String(64), nullable=True)         # ID of the currently executing step
    steps_completed = Column(Integer, default=0)
    total_steps = Column(Integer, default=0)

    # Context & State (The "memory" of the process)
    context = Column(JSON, default=dict)                     # Inputs and intermediate step results
    result = Column(JSON, default=dict)                      # Final outputs

    # Error / Escalation handling
    error_message = Column(Text, nullable=True)
    escalation_reason = Column(Text, nullable=True)
    assigned_to_user_id = Column(String, nullable=True)      # If waiting on human

    # Timing
    started_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    duration_ms = Column(Integer, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("ix_process_executions_status", "tenant_id", "department_id", "status"),
    )
