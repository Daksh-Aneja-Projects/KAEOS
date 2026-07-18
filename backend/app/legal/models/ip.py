"""
KAEOS Legal Domain — Intellectual Property Models
"""
from sqlalchemy import Column, String, DateTime, Text, Date, Enum
from sqlalchemy.sql import func
import uuid
import enum

from app.models.domain import Base

def _uuid():
    return str(uuid.uuid4())

class IPStatus(str, enum.Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    ABANDONED = "ABANDONED"
    EXPIRED = "EXPIRED"

class Patent(Base):
    """Corporate Patents issued or filed."""
    __tablename__ = "leg_patents"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)

    title = Column(String(256), nullable=False)
    patent_number = Column(String(64), nullable=True)
    application_number = Column(String(64), nullable=True)
    
    filing_date = Column(Date, nullable=True)
    issue_date = Column(Date, nullable=True)
    expiry_date = Column(Date, nullable=True)
    
    status = Column(Enum(IPStatus), default=IPStatus.PENDING)
    inventors = Column(Text, nullable=True)
    abstract = Column(Text, nullable=True)
    jurisdiction = Column(String(64), default="USA")

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

class Trademark(Base):
    """Corporate registered trademarks and service marks."""
    __tablename__ = "leg_trademarks"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)

    mark_name = Column(String(128), nullable=False)
    registration_number = Column(String(64), nullable=True)
    
    filing_date = Column(Date, nullable=True)
    registration_date = Column(Date, nullable=True)
    renewal_date = Column(Date, nullable=True)
    
    status = Column(Enum(IPStatus), default=IPStatus.PENDING)
    class_code = Column(String(32), nullable=True) # e.g. Class 9, Class 42
    jurisdiction = Column(String(64), default="USA")

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

class TradeSecret(Base):
    """Proprietary corporate assets (algorithms, architectures, codebases) treated as Trade Secrets."""
    __tablename__ = "leg_trade_secrets"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)

    asset_name = Column(String(256), nullable=False)
    description = Column(Text, nullable=True)
    custodian = Column(String(128), nullable=True)
    security_level = Column(String(32), default="RESTRICTED") # CONFIDENTIAL, RESTRICTED, TOP_SECRET

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
