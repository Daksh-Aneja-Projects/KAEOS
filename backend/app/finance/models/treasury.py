"""
KAEOS Finance Domain — Treasury & Cash Management Models
Bank accounts, cash flow tracking, and inter-account transfers.
"""
from sqlalchemy import Column, String, Integer, Float, DateTime, Boolean, ForeignKey, Enum, Date, Numeric
from sqlalchemy.sql import func
import uuid
import enum

from app.models.domain import Base

def _uuid():
    return str(uuid.uuid4())


class AccountClassification(str, enum.Enum):
    OPERATING = "OPERATING"
    PAYROLL = "PAYROLL"
    SAVINGS = "SAVINGS"
    INVESTMENT = "INVESTMENT"
    ESCROW = "ESCROW"
    PETTY_CASH = "PETTY_CASH"


class BankAccount(Base):
    """Company bank accounts tracked by treasury."""
    __tablename__ = "fin_bank_accounts"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)

    account_name = Column(String(128), nullable=False)
    bank_name = Column(String(128), nullable=False)
    account_number_masked = Column(String(20), nullable=False)  # Last 4 digits only
    routing_number = Column(String(16), nullable=True)
    swift_code = Column(String(16), nullable=True)
    classification = Column(Enum(AccountClassification), default=AccountClassification.OPERATING)
    currency = Column(String(3), default="USD")

    # Balances
    current_balance = Column(Numeric(18, 2), default=0)
    available_balance = Column(Numeric(18, 2), default=0)
    pending_deposits = Column(Numeric(18, 2), default=0)
    pending_withdrawals = Column(Numeric(18, 2), default=0)

    # GL mapping
    gl_account_id = Column(String, ForeignKey("fin_chart_of_accounts.id"), nullable=True)

    # Reconciliation
    last_reconciled_date = Column(Date, nullable=True)
    last_statement_balance = Column(Numeric(18, 2), nullable=True)
    reconciliation_difference = Column(Numeric(18, 2), default=0)

    is_active = Column(Boolean, default=True)
    is_primary = Column(Boolean, default=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class CashFlowType(str, enum.Enum):
    OPERATING_INFLOW = "OPERATING_INFLOW"
    OPERATING_OUTFLOW = "OPERATING_OUTFLOW"
    INVESTING_INFLOW = "INVESTING_INFLOW"
    INVESTING_OUTFLOW = "INVESTING_OUTFLOW"
    FINANCING_INFLOW = "FINANCING_INFLOW"
    FINANCING_OUTFLOW = "FINANCING_OUTFLOW"


class CashFlow(Base):
    """Cash flow entries for cash flow statement and forecasting."""
    __tablename__ = "fin_cash_flows"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    bank_account_id = Column(String, ForeignKey("fin_bank_accounts.id"), nullable=True)

    flow_date = Column(Date, nullable=False)
    flow_type = Column(Enum(CashFlowType), nullable=False)
    category = Column(String(64), nullable=True)             # "Payroll", "Revenue", "CapEx"
    description = Column(String(256), nullable=True)
    amount = Column(Numeric(18, 2), nullable=False)
    currency = Column(String(3), default="USD")

    # Source tracking
    source_module = Column(String(32), nullable=True)        # AP, AR, PAYROLL, MANUAL
    source_document_id = Column(String, nullable=True)

    # Forecasting
    is_forecast = Column(Boolean, default=False)             # True = projected, False = actual
    forecast_confidence = Column(Float, nullable=True)

    fiscal_period = Column(Integer, nullable=True)
    fiscal_year = Column(Integer, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())


class TransferStatus(str, enum.Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class Transfer(Base):
    """Inter-account fund transfers."""
    __tablename__ = "fin_transfers"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)

    from_account_id = Column(String, ForeignKey("fin_bank_accounts.id"), nullable=False)
    to_account_id = Column(String, ForeignKey("fin_bank_accounts.id"), nullable=False)

    amount = Column(Numeric(18, 2), nullable=False)
    currency = Column(String(3), default="USD")
    status = Column(Enum(TransferStatus), default=TransferStatus.PENDING)

    transfer_date = Column(Date, nullable=False)
    description = Column(String(256), nullable=True)
    reference = Column(String(64), nullable=True)

    # Approval
    requested_by = Column(String, nullable=True)
    approved_by = Column(String, nullable=True)
    approved_at = Column(DateTime(timezone=True), nullable=True)

    # GL posting
    journal_entry_id = Column(String, ForeignKey("fin_journal_entries.id"), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
