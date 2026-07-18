"""
KAEOS Legal Domain — Core Models
General legal matters and legal team roster.
"""
from sqlalchemy import Column, String, DateTime, Boolean, Enum, Text, ForeignKey
from sqlalchemy.sql import func
import uuid
import enum

from app.models.domain import Base

def _uuid():
    return str(uuid.uuid4())

class MatterStatus(str, enum.Enum):
    NEW = "NEW"
    IN_PROGRESS = "IN_PROGRESS"
    ON_HOLD = "ON_HOLD"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"

class MatterPriority(str, enum.Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"

class LegalTeamMember(Base):
    """Roster of internal legal team members (Attorneys, Paralegals, Compliance Officers)."""
    __tablename__ = "leg_team_members"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    
    name = Column(String(128), nullable=False)
    role = Column(String(64), nullable=False)  # General Counsel, Attorney, Compliance Lead, Paralegal
    email = Column(String(128), nullable=False, unique=True)
    bar_license_number = Column(String(64), nullable=True)
    is_active = Column(Boolean, default=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

class LegalMatter(Base):
    """Tracks general legal matters, internal files, counsel assignments, and resolutions."""
    __tablename__ = "leg_matters"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)

    title = Column(String(256), nullable=False)
    description = Column(Text, nullable=True)
    matter_type = Column(String(64), nullable=False) # M&A, Intellectual Property, Employment, Litigation, Corporate
    
    status = Column(Enum(MatterStatus), default=MatterStatus.NEW)
    priority = Column(Enum(MatterPriority), default=MatterPriority.MEDIUM)

    assigned_attorney_id = Column(String, ForeignKey("leg_team_members.id"), nullable=True)
    external_counsel = Column(String(256), nullable=True)
    estimated_exposure = Column(Text, nullable=True)
    resolution = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
