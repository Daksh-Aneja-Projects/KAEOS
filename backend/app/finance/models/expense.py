"""
KAEOS Finance Domain — Expense Management Models
Employee expense reports, line items, and policy enforcement.
"""
from sqlalchemy import Column, String, Integer, Float, DateTime, Boolean, JSON, ForeignKey, Enum, Date, Text, Numeric
from sqlalchemy.sql import func
import uuid
import enum

from app.models.domain import Base

def _uuid():
    return str(uuid.uuid4())


class ExpenseCategory(str, enum.Enum):
    TRAVEL = "TRAVEL"
    MEALS = "MEALS"
    LODGING = "LODGING"
    TRANSPORTATION = "TRANSPORTATION"
    OFFICE_SUPPLIES = "OFFICE_SUPPLIES"
    SOFTWARE = "SOFTWARE"
    HARDWARE = "HARDWARE"
    TRAINING = "TRAINING"
    CONFERENCES = "CONFERENCES"
    CLIENT_ENTERTAINMENT = "CLIENT_ENTERTAINMENT"
    TELECOMMUNICATIONS = "TELECOMMUNICATIONS"
    PROFESSIONAL_SERVICES = "PROFESSIONAL_SERVICES"
    OTHER = "OTHER"


class ExpenseReportStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    REIMBURSED = "REIMBURSED"
    PARTIALLY_REIMBURSED = "PARTIALLY_REIMBURSED"


class ExpenseReport(Base):
    """Employee-submitted expense report."""
    __tablename__ = "fin_expense_reports"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    employee_id = Column(String, ForeignKey("hr_employees.id"), nullable=False, index=True)

    report_number = Column(String(32), nullable=False, unique=True)
    title = Column(String(128), nullable=False)
    description = Column(Text, nullable=True)
    status = Column(Enum(ExpenseReportStatus), default=ExpenseReportStatus.DRAFT)

    # Amounts
    total_amount = Column(Numeric(18, 2), default=0)
    approved_amount = Column(Numeric(18, 2), default=0)
    reimbursed_amount = Column(Numeric(18, 2), default=0)
    currency = Column(String(3), default="USD")

    # Period
    expense_period_start = Column(Date, nullable=True)
    expense_period_end = Column(Date, nullable=True)
    submitted_at = Column(DateTime(timezone=True), nullable=True)

    # Approval workflow
    approver_id = Column(String, nullable=True)
    approved_at = Column(DateTime(timezone=True), nullable=True)
    rejection_reason = Column(Text, nullable=True)

    # AI
    ai_policy_violations = Column(JSON, default=list)        # [{rule, violation, severity}]
    ai_compliance_score = Column(Float, nullable=True)       # 0-100

    # GL posting
    gl_account_id = Column(String, ForeignKey("fin_chart_of_accounts.id"), nullable=True)
    journal_entry_id = Column(String, ForeignKey("fin_journal_entries.id"), nullable=True)
    cost_center = Column(String(64), nullable=True)
    department = Column(String(64), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ExpenseItem(Base):
    """Individual line item within an expense report."""
    __tablename__ = "fin_expense_items"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    report_id = Column(String, ForeignKey("fin_expense_reports.id"), nullable=False, index=True)

    expense_date = Column(Date, nullable=False)
    category = Column(Enum(ExpenseCategory), nullable=False)
    description = Column(String(256), nullable=False)
    merchant = Column(String(128), nullable=True)

    amount = Column(Numeric(18, 2), nullable=False)
    currency = Column(String(3), default="USD")
    exchange_rate = Column(Float, default=1.0)
    amount_in_base = Column(Numeric(18, 2), nullable=True)

    # Receipt
    receipt_path = Column(String(512), nullable=True)        # GCS/S3 URI
    receipt_verified = Column(Boolean, default=False)
    ai_receipt_data = Column(JSON, default=dict)             # OCR-extracted data

    # Policy
    is_within_policy = Column(Boolean, default=True)
    policy_violation_reason = Column(String(256), nullable=True)

    # Billable tracking
    is_billable = Column(Boolean, default=False)
    project_id = Column(String, nullable=True)
    client_id = Column(String, nullable=True)

    line_number = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class ExpensePolicy(Base):
    """Company expense policy rules — enforced by AI agent."""
    __tablename__ = "fin_expense_policies"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)

    name = Column(String(128), nullable=False)
    category = Column(Enum(ExpenseCategory), nullable=True)  # NULL = applies to all
    description = Column(Text, nullable=True)

    # Limits
    max_amount_per_item = Column(Numeric(18, 2), nullable=True)
    max_amount_per_report = Column(Numeric(18, 2), nullable=True)
    max_daily_total = Column(Numeric(18, 2), nullable=True)
    receipt_required_above = Column(Numeric(18, 2), default=25.00)

    # Approval thresholds
    auto_approve_below = Column(Numeric(18, 2), default=100.00)
    manager_approval_below = Column(Numeric(18, 2), default=5000.00)
    # Above manager_approval_below → requires VP/finance approval

    is_active = Column(Boolean, default=True)
    effective_date = Column(Date, nullable=True)
    expiry_date = Column(Date, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
