"""
KAEOS Sales Domain — Leads Models
"""
from sqlalchemy import Column, String, DateTime, Enum, ForeignKey, Integer, Boolean
from sqlalchemy.sql import func
import uuid
import enum

from app.models.domain import Base

def _uuid():
    return str(uuid.uuid4())

class LeadSource(str, enum.Enum):
    WEBSITE = "WEBSITE"
    REFERRAL = "REFERRAL"
    OUTBOUND = "OUTBOUND"
    CONFERENCE = "CONFERENCE"
    MARKETPLACE = "MARKETPLACE"

class Lead(Base):
    """Marketing and sales leads before opportunity conversion."""
    __tablename__ = "sls_leads"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)

    company = Column(String(256), nullable=False)
    contact_name = Column(String(128), nullable=False)
    email = Column(String(128), nullable=False)
    phone = Column(String(32), nullable=True)
    
    source = Column(Enum(LeadSource), default=LeadSource.WEBSITE)
    is_converted = Column(Boolean, default=False)
    converted_opportunity_id = Column(String, nullable=True)
    
    assigned_rep_id = Column(String, ForeignKey("sls_reps.id"), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

class LeadScore(Base):
    """AI lead scores calculating Ideal Customer Profile (ICP) match and intent signals."""
    __tablename__ = "sls_lead_scores"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    lead_id = Column(String, ForeignKey("sls_leads.id"), nullable=False, index=True)

    icp_score = Column(Integer, default=0) # 0 to 100
    intent_score = Column(Integer, default=0) # 0 to 100
    overall_score = Column(Integer, default=0) # Weighted sum
    
    factors = Column(String(512), nullable=True) # JSON array of features (e.g. "Matches employee count tier")

    created_at = Column(DateTime(timezone=True), server_default=func.now())
