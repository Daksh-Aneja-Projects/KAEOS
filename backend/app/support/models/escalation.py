"""
KAEOS Support Domain — Escalation Models
"""
from sqlalchemy import Column, String, DateTime, ForeignKey, Integer, Boolean, Text
from sqlalchemy.sql import func
import uuid

from app.models.domain import Base

def _uuid():
    return str(uuid.uuid4())

class EscalationRule(Base):
    """Rules specifying when a ticket should escalate to higher support tier or manager."""
    __tablename__ = "sup_escalation_rules"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)

    rule_name = Column(String(128), nullable=False)
    trigger_condition = Column(String(256), nullable=False) # e.g. "SLA_BREACH_RESPONSE", "VIP_CUSTOMER_HIGH_PRIORITY"
    
    escalate_to_team_id = Column(String, ForeignKey("sup_teams.id"), nullable=True)
    escalate_to_agent_id = Column(String, ForeignKey("sup_agents.id"), nullable=True)
    
    time_threshold_mins = Column(Integer, default=30)
    is_active = Column(Boolean, default=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

class EscalationEvent(Base):
    """Logs documenting past escalation actions."""
    __tablename__ = "sup_escalation_events"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    ticket_id = Column(String, ForeignKey("sup_tickets.id"), nullable=False, index=True)
    rule_id = Column(String, ForeignKey("sup_escalation_rules.id"), nullable=True)

    escalated_from_agent_id = Column(String, nullable=True)
    escalated_to_agent_id = Column(String, nullable=True)
    reason = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
