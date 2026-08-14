"""
KAEOS Lending Domain - Core Models

The banking-lending vertical's system of record: loan applications, the
underwriting decisions made on them, adverse-action notices, and the credit
policy the underwriter enforces.

Protected-class attributes ARE stored on the application (they are required to
run fair-lending / disparate-impact analysis) but are access-controlled: they
must never feed the deterministic credit decision, only the portfolio-level
four-fifths monitoring. Money is Numeric(18,2); every row is tenant-scoped.
"""
from sqlalchemy import (Boolean, Column, Date, DateTime, ForeignKey, Integer,
                        JSON, Numeric, String, Text, UniqueConstraint)
from sqlalchemy.sql import func
import enum
import uuid

from app.models.domain import Base


def _uuid():
    return str(uuid.uuid4())


class LoanStatus(str, enum.Enum):
    RECEIVED = "RECEIVED"
    IN_REVIEW = "IN_REVIEW"
    PENDING_HITL = "PENDING_HITL"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"


class LoanApplication(Base):
    """A consumer credit application. Business key (tenant_id, application_number)
    is tenant-scoped, never globally unique."""
    __tablename__ = "lnd_loan_applications"
    __table_args__ = (
        UniqueConstraint("tenant_id", "application_number",
                         name="uq_lnd_app_tenant_number"),
    )

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)

    application_number = Column(String(32), nullable=False)
    applicant_name = Column(String(160), nullable=False)
    applicant_ref = Column(String(64), nullable=True)     # external CRM/borrower id

    product = Column(String(48), nullable=False, default="personal_loan")
    credit_purpose = Column(String(24), nullable=False, default="consumer")  # consumer|business
    amount = Column(Numeric(18, 2), nullable=False)
    term_months = Column(Integer, nullable=True)

    # Underwriting inputs (permissible, credit-related).
    credit_score = Column(Integer, nullable=True)
    annual_income = Column(Numeric(18, 2), nullable=True)
    monthly_debt = Column(Numeric(18, 2), nullable=True)
    dti_ratio = Column(Numeric(9, 4), nullable=True)       # debt-to-income, 0..n

    # Protected-class attributes - stored ONLY for fair-lending analysis, never
    # an underwriting input. Access-controlled at the service/router layer.
    protected_class = Column(JSON, default=dict)           # {race, ethnicity, gender, age_band, marital_status}

    status = Column(String(16), nullable=False, default=LoanStatus.RECEIVED.value)
    intake_score = Column(Numeric(9, 4), nullable=True)    # deterministic 0..1 score

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class UnderwritingDecision(Base):
    """The deterministic credit decision on an application. `reasons` are the
    specific principal reasons (the same list Reg B requires on a denial)."""
    __tablename__ = "lnd_underwriting_decisions"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    application_id = Column(String, ForeignKey("lnd_loan_applications.id"),
                            nullable=False, index=True)

    decision = Column(String(16), nullable=False)          # APPROVE|DENY|REFER
    reasons = Column(JSON, default=list)                   # [str, ...] specific principal reasons
    confidence = Column(Numeric(9, 4), nullable=True)
    decided_by = Column(String(160), nullable=True)        # attributable principal
    decided_at = Column(DateTime(timezone=True), server_default=func.now())

    # TILA/Reg Z disclosures captured at approval (nullable on a denial).
    apr = Column(Numeric(9, 4), nullable=True)
    finance_charge = Column(Numeric(18, 2), nullable=True)
    amount_financed = Column(Numeric(18, 2), nullable=True)
    total_of_payments = Column(Numeric(18, 2), nullable=True)

    gate_status = Column(String(32), nullable=True)        # governance gate outcome
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class AdverseActionNotice(Base):
    """ECOA/Reg B adverse-action notice for a denial - specific reasons, sent
    within 30 days of the decision (12 CFR 1002.9)."""
    __tablename__ = "lnd_adverse_action_notices"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    application_id = Column(String, ForeignKey("lnd_loan_applications.id"),
                            nullable=False, index=True)
    decision_id = Column(String, ForeignKey("lnd_underwriting_decisions.id"), nullable=True)

    specific_reasons = Column(JSON, default=list)          # [str, ...]
    body = Column(Text, nullable=True)                     # rendered notice text
    decision_date = Column(Date, nullable=True)
    sent_at = Column(DateTime(timezone=True), nullable=True)
    within_30_days = Column(Boolean, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())


class CreditPolicy(Base):
    """Tenant credit-policy thresholds the underwriter enforces deterministically.
    Absence of a row falls back to conservative built-in defaults in the service."""
    __tablename__ = "lnd_credit_policies"
    __table_args__ = (
        UniqueConstraint("tenant_id", "product", name="uq_lnd_policy_tenant_product"),
    )

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)

    product = Column(String(48), nullable=False, default="personal_loan")
    min_credit_score = Column(Integer, nullable=False, default=640)
    max_dti_ratio = Column(Numeric(9, 4), nullable=False, default=0.45)
    min_annual_income = Column(Numeric(18, 2), nullable=False, default=24000)
    max_amount = Column(Numeric(18, 2), nullable=False, default=50000)
    base_apr = Column(Numeric(9, 4), nullable=False, default=12.5)
    is_active = Column(Boolean, default=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
