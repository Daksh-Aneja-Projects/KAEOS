"""
KAEOS Legal Domain — Litigation Models
"""
from sqlalchemy import Column, String, DateTime, Text, Date, ForeignKey, Numeric, Enum
from sqlalchemy.sql import func
import uuid
import enum

from app.models.domain import Base

def _uuid():
    return str(uuid.uuid4())

class CaseStage(str, enum.Enum):
    PLEADING = "PLEADING"
    DISCOVERY = "DISCOVERY"
    MOTION = "MOTION"
    TRIAL = "TRIAL"
    APPEAL = "APPEAL"
    SETTLED = "SETTLED"
    DISMISSED = "DISMISSED"

class Case(Base):
    """Active or historic court cases involving the corporation."""
    __tablename__ = "leg_cases"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)

    case_name = Column(String(256), nullable=False) # e.g. "Acme Corp v. Beta LLC"
    case_number = Column(String(64), nullable=True)
    court = Column(String(128), nullable=True)
    
    stage = Column(Enum(CaseStage), default=CaseStage.PLEADING)
    exposure_amount = Column(Numeric(18, 2), default=0)
    
    opposing_party = Column(String(256), nullable=False)
    opposing_counsel = Column(String(256), nullable=True)
    lead_attorney_id = Column(String, ForeignKey("leg_team_members.id"), nullable=True)
    
    description = Column(Text, nullable=True)
    outcome = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

class CaseEvent(Base):
    """Timeline events for court litigation (hearings, deposition dates, discovery requests)."""
    __tablename__ = "leg_case_events"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    case_id = Column(String, ForeignKey("leg_cases.id"), nullable=False, index=True)

    event_title = Column(String(256), nullable=False)
    event_date = Column(Date, nullable=False)
    description = Column(Text, nullable=True)
    is_milestone = Column(Text, default="No")

    created_at = Column(DateTime(timezone=True), server_default=func.now())

class CourtFiling(Base):
    """Submissions, summons, briefs filed in court."""
    __tablename__ = "leg_court_filings"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    case_id = Column(String, ForeignKey("leg_cases.id"), nullable=False, index=True)

    document_name = Column(String(256), nullable=False)
    filing_date = Column(Date, nullable=False)
    filed_by = Column(String(128), nullable=True)
    document_path = Column(String(512), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
