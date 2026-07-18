"""
KAEOS Finance Domain — Tax Models
Tax filings, rules, and withholding configurations.
"""
from sqlalchemy import Column, String, Integer, Float, DateTime, Boolean, JSON, ForeignKey, Enum, Date, Text, Numeric
from sqlalchemy.sql import func
import uuid
import enum

from app.models.domain import Base

def _uuid():
    return str(uuid.uuid4())


class FilingStatus(str, enum.Enum):
    NOT_STARTED = "NOT_STARTED"
    IN_PROGRESS = "IN_PROGRESS"
    READY_FOR_REVIEW = "READY_FOR_REVIEW"
    FILED = "FILED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    AMENDED = "AMENDED"


class TaxFiling(Base):
    """Tax filing record — federal, state, or local."""
    __tablename__ = "fin_tax_filings"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)

    filing_type = Column(String(32), nullable=False)         # INCOME, SALES, PAYROLL, PROPERTY, VAT
    jurisdiction = Column(String(64), nullable=False)        # "Federal", "CA", "NY", "EU-DE"
    period = Column(String(16), nullable=False)              # "2026-Q1", "2026-01"
    fiscal_year = Column(Integer, nullable=False)
    status = Column(Enum(FilingStatus), default=FilingStatus.NOT_STARTED)

    # Amounts
    taxable_amount = Column(Numeric(18, 2), default=0)
    tax_liability = Column(Numeric(18, 2), default=0)
    tax_paid = Column(Numeric(18, 2), default=0)
    balance_due = Column(Numeric(18, 2), default=0)
    penalties = Column(Numeric(18, 2), default=0)

    # Dates
    due_date = Column(Date, nullable=False)
    filed_date = Column(Date, nullable=True)
    extended_due_date = Column(Date, nullable=True)

    # Reference
    confirmation_number = Column(String(64), nullable=True)
    form_number = Column(String(16), nullable=True)          # "1120", "941", "Sales Tax"
    filing_method = Column(String(16), default="ELECTRONIC") # ELECTRONIC, PAPER

    # AI
    ai_risk_assessment = Column(JSON, default=dict)          # {risk_level, flags, recommendations}

    prepared_by = Column(String, nullable=True)
    reviewed_by = Column(String, nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class TaxRule(Base):
    """Tax rules and rates by jurisdiction."""
    __tablename__ = "fin_tax_rules"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)

    name = Column(String(128), nullable=False)
    tax_type = Column(String(32), nullable=False)            # INCOME, SALES, PAYROLL, PROPERTY, VAT
    jurisdiction = Column(String(64), nullable=False)
    rate = Column(Float, nullable=False)                     # e.g., 0.21 for 21%
    effective_date = Column(Date, nullable=False)
    expiry_date = Column(Date, nullable=True)

    # Thresholds
    threshold_min = Column(Numeric(18, 2), nullable=True)    # Bracket minimum
    threshold_max = Column(Numeric(18, 2), nullable=True)
    is_progressive = Column(Boolean, default=False)

    # Exemptions
    exemptions = Column(JSON, default=list)                  # List of exempt categories
    description = Column(Text, nullable=True)
    source_url = Column(String(512), nullable=True)          # Link to regulation

    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class WithholdingConfig(Base):
    """Employee tax withholding configuration (links to HR)."""
    __tablename__ = "fin_withholding_configs"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    employee_id = Column(String, ForeignKey("hr_employees.id"), nullable=False, index=True)

    filing_status = Column(String(32), default="SINGLE")     # SINGLE, MARRIED_JOINTLY, HEAD_OF_HOUSEHOLD
    federal_allowances = Column(Integer, default=0)
    state = Column(String(4), nullable=True)
    state_allowances = Column(Integer, default=0)
    additional_withholding = Column(Numeric(18, 2), default=0)

    # W-4 data
    w4_year = Column(Integer, nullable=True)
    exempt_from_withholding = Column(Boolean, default=False)

    effective_date = Column(Date, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
