"""
KAEOS Finance Domain — Financial Reporting Models
Generated reports (P&L, Balance Sheet, Cash Flow) and scheduling.
"""
from sqlalchemy import Column, String, Integer, DateTime, Boolean, JSON, Enum, Date, Text
from sqlalchemy.sql import func
import uuid
import enum

from app.models.domain import Base

def _uuid():
    return str(uuid.uuid4())


class ReportType(str, enum.Enum):
    INCOME_STATEMENT = "INCOME_STATEMENT"      # P&L
    BALANCE_SHEET = "BALANCE_SHEET"
    CASH_FLOW_STATEMENT = "CASH_FLOW_STATEMENT"
    TRIAL_BALANCE = "TRIAL_BALANCE"
    AGED_RECEIVABLES = "AGED_RECEIVABLES"
    AGED_PAYABLES = "AGED_PAYABLES"
    BUDGET_VS_ACTUAL = "BUDGET_VS_ACTUAL"
    GENERAL_LEDGER = "GENERAL_LEDGER"
    EXPENSE_SUMMARY = "EXPENSE_SUMMARY"
    CUSTOM = "CUSTOM"


class ReportStatus(str, enum.Enum):
    GENERATING = "GENERATING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    ARCHIVED = "ARCHIVED"


class FinancialReport(Base):
    """Generated financial report snapshot."""
    __tablename__ = "fin_reports"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)

    report_type = Column(Enum(ReportType), nullable=False)
    title = Column(String(256), nullable=False)
    description = Column(Text, nullable=True)
    status = Column(Enum(ReportStatus), default=ReportStatus.GENERATING)

    # Period
    period_start = Column(Date, nullable=False)
    period_end = Column(Date, nullable=False)
    fiscal_year = Column(Integer, nullable=True)
    comparative_period = Column(Boolean, default=False)      # Include prior period comparison

    # Filters
    department = Column(String(64), nullable=True)
    cost_center = Column(String(64), nullable=True)
    currency = Column(String(3), default="USD")

    # Report data (JSON for flexibility, could be large)
    report_data = Column(JSON, default=dict)                 # Full structured report content
    summary = Column(JSON, default=dict)                     # Key totals: revenue, expenses, net_income

    # Generation metadata
    generated_by = Column(String, nullable=True)             # "AI" or user ID
    generated_at = Column(DateTime(timezone=True), nullable=True)
    generation_time_ms = Column(Integer, nullable=True)

    # AI insights
    ai_commentary = Column(Text, nullable=True)              # AI-generated narrative
    ai_anomalies = Column(JSON, default=list)                # [{metric, expected, actual, severity}]

    # Export
    export_path = Column(String(512), nullable=True)         # GCS/S3 URI for PDF/Excel

    created_at = Column(DateTime(timezone=True), server_default=func.now())


class ReportSchedule(Base):
    """Scheduled report generation — daily, weekly, monthly."""
    __tablename__ = "fin_report_schedules"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)

    name = Column(String(128), nullable=False)
    report_type = Column(Enum(ReportType), nullable=False)
    frequency = Column(String(16), nullable=False)           # DAILY, WEEKLY, MONTHLY, QUARTERLY
    cron_expression = Column(String(32), nullable=True)      # For custom schedules

    # Config
    filters = Column(JSON, default=dict)                     # {department, cost_center, etc.}
    recipients = Column(JSON, default=list)                  # Email addresses to send to
    format = Column(String(8), default="PDF")                # PDF, EXCEL, CSV

    is_active = Column(Boolean, default=True)
    last_run_at = Column(DateTime(timezone=True), nullable=True)
    next_run_at = Column(DateTime(timezone=True), nullable=True)

    created_by = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
