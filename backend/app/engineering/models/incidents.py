"""
KAEOS Engineering Domain — Incident Models (IT Ops)
"""
from sqlalchemy import Column, String, DateTime, Enum, Text, Integer, Boolean, JSON, ForeignKey
from sqlalchemy.sql import func
import uuid
import enum

from app.models.domain import Base


def _uuid():
    return str(uuid.uuid4())


class IncidentSeverity(str, enum.Enum):
    SEV1 = "SEV1"   # full outage, revenue impacting
    SEV2 = "SEV2"   # major degradation
    SEV3 = "SEV3"   # minor degradation
    SEV4 = "SEV4"   # cosmetic / no customer impact


class IncidentStatus(str, enum.Enum):
    DETECTED = "DETECTED"
    TRIAGED = "TRIAGED"
    MITIGATING = "MITIGATING"
    MONITORING = "MONITORING"
    RESOLVED = "RESOLVED"
    POSTMORTEM_DUE = "POSTMORTEM_DUE"
    CLOSED = "CLOSED"


class Incident(Base):
    """A production incident — the unit the incident agent triages."""
    __tablename__ = "eng_incidents"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    service_id = Column(String, ForeignKey("eng_services.id"), nullable=True, index=True)

    incident_number = Column(String(32), nullable=False)
    title = Column(String(256), nullable=False)
    description = Column(Text, nullable=True)

    severity = Column(Enum(IncidentSeverity), default=IncidentSeverity.SEV3)
    status = Column(Enum(IncidentStatus), default=IncidentStatus.DETECTED)

    commander_id = Column(String, ForeignKey("eng_engineers.id"), nullable=True)
    detected_by = Column(String(64), nullable=True)   # ALERT | CUSTOMER | ENGINEER
    customer_impacting = Column(Boolean, default=False)
    affected_users = Column(Integer, nullable=True)

    # Suspected trigger — lets the agent correlate deploys to incidents.
    suspected_deployment_id = Column(String, ForeignKey("eng_deployments.id"), nullable=True)

    # AI triage output.
    ai_severity_assessment = Column(String(16), nullable=True)
    ai_probable_cause = Column(Text, nullable=True)
    ai_recommended_action = Column(Text, nullable=True)
    ai_triaged_at = Column(DateTime(timezone=True), nullable=True)

    detected_at = Column(DateTime(timezone=True), server_default=func.now())
    acknowledged_at = Column(DateTime(timezone=True), nullable=True)
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    time_to_acknowledge_mins = Column(Integer, nullable=True)
    time_to_resolve_mins = Column(Integer, nullable=True)


class Postmortem(Base):
    """Blameless postmortem with action items — the learning artifact."""
    __tablename__ = "eng_postmortems"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    incident_id = Column(String, ForeignKey("eng_incidents.id"), nullable=False, index=True)

    summary = Column(Text, nullable=True)
    root_cause = Column(Text, nullable=True)
    contributing_factors = Column(JSON, default=list)
    action_items = Column(JSON, default=list)   # [{"action":..., "owner":..., "due":..., "done":bool}]

    published = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
