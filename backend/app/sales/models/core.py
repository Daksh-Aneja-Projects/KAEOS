"""
KAEOS Sales Domain — Core Models
Sales reps, teams, and territories.
"""
from sqlalchemy import Column, String, DateTime, Boolean, Numeric, ForeignKey
from sqlalchemy.sql import func
import uuid

from app.models.domain import Base

def _uuid():
    return str(uuid.uuid4())

class SalesTeam(Base):
    """Sales teams (e.g. North America Enterprise, EMEA Mid-Market)."""
    __tablename__ = "sls_teams"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)

    name = Column(String(128), nullable=False)
    region = Column(String(64), nullable=False)  # AMER, EMEA, APAC
    quota_annual = Column(Numeric(18, 2), default=0)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

class SalesRep(Base):
    """Sales representatives, account executives, and business development reps."""
    __tablename__ = "sls_reps"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)

    name = Column(String(128), nullable=False)
    email = Column(String(128), nullable=False, unique=True)
    team_id = Column(String, ForeignKey("sls_teams.id"), nullable=True)
    
    quota_ytd = Column(Numeric(18, 2), default=0)
    attainment_ytd = Column(Numeric(18, 2), default=0)
    is_active = Column(Boolean, default=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

class Territory(Base):
    """Geographic or segment definitions mapping accounts to sales reps."""
    __tablename__ = "sls_territories"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)

    name = Column(String(128), nullable=False)
    segment = Column(String(64), default="ENTERPRISE")  # ENTERPRISE, MID_MARKET, SMB
    assigned_rep_id = Column(String, ForeignKey("sls_reps.id"), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
