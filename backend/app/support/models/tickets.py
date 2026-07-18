"""
KAEOS Support Domain — Tickets Models
"""
from sqlalchemy import Column, String, DateTime, Enum, Text, ForeignKey
from sqlalchemy.sql import func
import uuid
import enum

from app.models.domain import Base

def _uuid():
    return str(uuid.uuid4())

class TicketPriority(str, enum.Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    URGENT = "URGENT"

class TicketStatus(str, enum.Enum):
    NEW = "NEW"
    ASSIGNED = "ASSIGNED"
    OPEN = "OPEN"
    PENDING_CUSTOMER = "PENDING_CUSTOMER"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"

class Ticket(Base):
    """Customer support tickets/incidents."""
    __tablename__ = "sup_tickets"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)

    ticket_number = Column(String(32), nullable=False, unique=True)
    customer_id = Column(String, nullable=True) # Linked customer reference
    
    subject = Column(String(256), nullable=False)
    description = Column(Text, nullable=False)
    
    status = Column(Enum(TicketStatus), default=TicketStatus.NEW)
    priority = Column(Enum(TicketPriority), default=TicketPriority.MEDIUM)
    
    assigned_agent_id = Column(String, ForeignKey("sup_agents.id"), nullable=True)
    assigned_team_id = Column(String, ForeignKey("sup_teams.id"), nullable=True)
    
    channel_id = Column(String, ForeignKey("sup_channels.id"), nullable=True)
    
    # SLA metrics
    first_response_at = Column(DateTime(timezone=True), nullable=True)
    resolved_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

class TicketComment(Base):
    """Conversation history for tickets (comments, emails, chat transcripts)."""
    __tablename__ = "sup_ticket_comments"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    ticket_id = Column(String, ForeignKey("sup_tickets.id"), nullable=False, index=True)
    
    author_type = Column(String(32), nullable=False)  # CUSTOMER, AGENT, SYSTEM
    author_id = Column(String, nullable=True)
    body = Column(Text, nullable=False)
    is_internal = Column(Text, default="No")

    created_at = Column(DateTime(timezone=True), server_default=func.now())

class TicketTag(Base):
    """Categories mapped to tickets for analysis (e.g. login_issue, refund_request)."""
    __tablename__ = "sup_ticket_tags"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    ticket_id = Column(String, ForeignKey("sup_tickets.id"), nullable=False, index=True)
    tag = Column(String(64), nullable=False, index=True)
