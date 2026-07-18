"""
KAEOS Legal Domain — Contracts Models
"""
from sqlalchemy import Column, String, DateTime, Enum, Text, ForeignKey, Numeric, Date, Boolean
from sqlalchemy.sql import func
import uuid
import enum

from app.models.domain import Base

def _uuid():
    return str(uuid.uuid4())

class ContractStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    IN_REVIEW = "IN_REVIEW"
    APPROVED = "APPROVED"
    SIGNED = "SIGNED"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    TERMINATED = "TERMINATED"

class ClauseRiskLevel(str, enum.Enum):
    NONE = "NONE"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"

class Contract(Base):
    """Corporate contracts (NDAs, MSAs, SOWs, Employment Agreements)."""
    __tablename__ = "leg_contracts"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)

    title = Column(String(256), nullable=False)
    counterparty = Column(String(256), nullable=False)
    contract_type = Column(String(64), nullable=False)  # NDA, MSA, SOW, License
    
    status = Column(Enum(ContractStatus), default=ContractStatus.DRAFT)
    contract_value = Column(Numeric(18, 2), nullable=True)
    
    effective_date = Column(Date, nullable=True)
    expiry_date = Column(Date, nullable=True)
    auto_renew = Column(Boolean, default=False)
    
    owner_id = Column(String, nullable=True)  # Associated employee ID
    document_path = Column(String(512), nullable=True)
    
    ai_risk_score = Column(Numeric(5, 2), nullable=True)  # 0.00 to 100.00
    ai_summary = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

class ContractClause(Base):
    """Individual legal clauses in contracts, analyzed by AI for risk factors (e.g. Indemnification, Limitation of Liability)."""
    __tablename__ = "leg_contract_clauses"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    contract_id = Column(String, ForeignKey("leg_contracts.id"), nullable=False, index=True)

    clause_type = Column(String(64), nullable=False)  # Indemnity, Governing_Law, Limitation_of_Liability
    original_text = Column(Text, nullable=False)
    suggested_text = Column(Text, nullable=True)
    
    risk_level = Column(Enum(ClauseRiskLevel), default=ClauseRiskLevel.NONE)
    ai_analysis = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

class ContractTemplate(Base):
    """Standard legal boilerplate templates."""
    __tablename__ = "leg_contract_templates"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)

    name = Column(String(128), nullable=False)
    contract_type = Column(String(64), nullable=False)
    content = Column(Text, nullable=False)
    version = Column(String(10), default="1.0.0")
    is_active = Column(Boolean, default=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
