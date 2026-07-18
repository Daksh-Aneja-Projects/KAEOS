"""
KAEOS Support Domain — SLA Models
"""
from sqlalchemy import Column, String, DateTime, ForeignKey, Integer, Numeric, Boolean
from sqlalchemy.sql import func
import uuid

from app.models.domain import Base

def _uuid():
    return str(uuid.uuid4())

class SLAPolicy(Base):
    """SLA metrics per priority level (targets for response and resolution times)."""
    __tablename__ = "sup_sla_policies"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)

    name = Column(String(128), nullable=False)
    priority_level = Column(String(32), nullable=False) # LOW, MEDIUM, HIGH, URGENT
    
    response_target_mins = Column(Integer, nullable=False)
    resolution_target_hrs = Column(Integer, nullable=False)
    is_active = Column(Boolean, default=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

class SLABreach(Base):
    """Logs of SLA breaches for reporting and manager escalation."""
    __tablename__ = "sup_sla_breaches"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    ticket_id = Column(String, ForeignKey("sup_tickets.id"), nullable=False, index=True)
    policy_id = Column(String, ForeignKey("sup_sla_policies.id"), nullable=False)

    breach_type = Column(String(32), nullable=False)  # FIRST_RESPONSE, RESOLUTION
    minutes_over = Column(Integer, nullable=False)
    is_acknowledged = Column(Boolean, default=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

class SLAMetric(Base):
    """Daily/weekly aggregate metrics for SLA reporting."""
    __tablename__ = "sup_sla_metrics"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)

    date_label = Column(String(32), nullable=False)  # YYYY-MM-DD
    total_tickets = Column(Integer, default=0)
    breached_tickets = Column(Integer, default=0)
    compliance_rate = Column(Numeric(5, 2), nullable=True) # 0.00 to 100.00

    created_at = Column(DateTime(timezone=True), server_default=func.now())
