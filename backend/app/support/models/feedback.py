"""
KAEOS Support Domain — Feedback Models
"""
from sqlalchemy import Column, String, DateTime, ForeignKey, Integer, Text, Numeric
from sqlalchemy.sql import func
import uuid

from app.models.domain import Base

def _uuid():
    return str(uuid.uuid4())

class CustomerSatisfaction(Base):
    """CSAT survey logs sent after ticket resolutions."""
    __tablename__ = "sup_csat_surveys"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    ticket_id = Column(String, ForeignKey("sup_tickets.id"), nullable=False, index=True)

    rating = Column(Integer, nullable=False) # 1 to 5 stars
    comment = Column(Text, nullable=True)
    sentiment = Column(String(32), nullable=True) # POSITIVE, NEUTRAL, NEGATIVE
    
    completed_at = Column(DateTime(timezone=True), server_default=func.now())

class NPS_Survey(Base):
    """Net Promoter Score (NPS) corporate surveys."""
    __tablename__ = "sup_nps_surveys"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)

    customer_id = Column(String, nullable=False)
    score = Column(Integer, nullable=False) # 0 to 10
    feedback_text = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

class FeedbackTheme(Base):
    """Aggregated feedback trends extracted by AI sentiment models."""
    __tablename__ = "sup_feedback_themes"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)

    theme_name = Column(String(128), nullable=False)
    volume_percentage = Column(Numeric(5, 2), nullable=True)
    severity_rating = Column(String(32), default="MEDIUM") # LOW, MEDIUM, HIGH

    created_at = Column(DateTime(timezone=True), server_default=func.now())
