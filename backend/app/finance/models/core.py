"""
KAEOS Finance Domain — Core Accounting Models
Chart of Accounts, Journal Entries, and General Ledger line items.
"""
from sqlalchemy import Column, String, Integer, Float, DateTime, Boolean, JSON, ForeignKey, Enum, Date, Text, Numeric, UniqueConstraint
from sqlalchemy.sql import func
import enum

from app.models.domain import Base
from app.models.mixins import new_uuid as _uuid



class AccountType(str, enum.Enum):
    ASSET = "ASSET"
    LIABILITY = "LIABILITY"
    EQUITY = "EQUITY"
    REVENUE = "REVENUE"
    EXPENSE = "EXPENSE"
    CONTRA_ASSET = "CONTRA_ASSET"
    CONTRA_LIABILITY = "CONTRA_LIABILITY"
    CONTRA_REVENUE = "CONTRA_REVENUE"


class ChartOfAccount(Base):
    """Chart of Accounts — master list of all GL accounts."""
    __tablename__ = "fin_chart_of_accounts"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)

    account_code = Column(String(20), nullable=False)     # e.g., "1010", "4200"
    account_name = Column(String(128), nullable=False)     # e.g., "Cash and Equivalents"
    account_type = Column(Enum(AccountType), nullable=False)
    parent_account_id = Column(String, ForeignKey("fin_chart_of_accounts.id"), nullable=True)

    description = Column(Text, nullable=True)
    currency = Column(String(3), default="USD")            # ISO 4217
    is_active = Column(Boolean, default=True)
    is_reconcilable = Column(Boolean, default=True)
    is_bank_account = Column(Boolean, default=False)

    # Classification tags for reporting
    department = Column(String(64), nullable=True)
    cost_center = Column(String(64), nullable=True)
    tags = Column(JSON, default=list)

    normal_balance = Column(String(6), default="DEBIT")    # DEBIT or CREDIT
    current_balance = Column(Numeric(18, 2), default=0)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class JournalEntryStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    POSTED = "POSTED"
    REVERSED = "REVERSED"
    VOIDED = "VOIDED"


class JournalEntry(Base):
    """Double-entry journal entries — the atomic unit of accounting."""
    __tablename__ = "fin_journal_entries"
    # Tenant-scoped business key: global unique caused cross-tenant collisions.
    __table_args__ = (
        UniqueConstraint("tenant_id", "entry_number", name="uq_fin_je_tenant_number"),
    )

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)

    entry_number = Column(String(32), nullable=False)
    entry_date = Column(Date, nullable=False)
    posting_date = Column(Date, nullable=True)

    description = Column(Text, nullable=False)
    reference = Column(String(128), nullable=True)          # Invoice #, PO #, etc.
    source_module = Column(String(32), nullable=True)        # AP, AR, PAYROLL, MANUAL
    source_document_id = Column(String, nullable=True)       # FK to originating document

    status = Column(Enum(JournalEntryStatus), default=JournalEntryStatus.DRAFT)
    total_debit = Column(Numeric(18, 2), default=0)
    total_credit = Column(Numeric(18, 2), default=0)

    # Approval
    created_by = Column(String, nullable=True)
    approved_by = Column(String, nullable=True)
    approved_at = Column(DateTime(timezone=True), nullable=True)

    # AI-assisted
    ai_categorized = Column(Boolean, default=False)
    ai_confidence = Column(Float, nullable=True)

    # Audit
    fiscal_year = Column(Integer, nullable=True)
    fiscal_period = Column(Integer, nullable=True)           # 1-12 or 1-13

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class JournalLine(Base):
    """Individual debit/credit line within a journal entry."""
    __tablename__ = "fin_journal_lines"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    journal_entry_id = Column(String, ForeignKey("fin_journal_entries.id"), nullable=False, index=True)
    account_id = Column(String, ForeignKey("fin_chart_of_accounts.id"), nullable=False, index=True)

    description = Column(String(256), nullable=True)
    debit = Column(Numeric(18, 2), default=0)
    credit = Column(Numeric(18, 2), default=0)

    # Dimensional analysis
    department = Column(String(64), nullable=True)
    cost_center = Column(String(64), nullable=True)
    project_id = Column(String, nullable=True)

    # Currency handling
    currency = Column(String(3), default="USD")
    exchange_rate = Column(Float, default=1.0)
    amount_in_base = Column(Numeric(18, 2), nullable=True)  # Amount after FX conversion

    line_number = Column(Integer, nullable=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now())


class FXRate(Base):
    """Exchange rate: how many units of the tenant base currency one unit of
    ``currency`` is worth, effective ``as_of``. post_journal_entry converts every
    foreign-currency line to base at the most recent rate on/before the entry
    date; a line whose account currency has no such rate is refused."""
    __tablename__ = "fin_fx_rates"
    __table_args__ = (
        UniqueConstraint("tenant_id", "currency", "as_of", name="uq_fin_fx_tenant_ccy_asof"),
    )

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)

    currency = Column(String(3), nullable=False)          # ISO 4217, the FROM currency
    base_currency = Column(String(3), nullable=False, default="USD")
    rate = Column(Numeric(18, 8), nullable=False)          # base units per 1 unit of currency
    as_of = Column(Date, nullable=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now())


class FiscalPeriodStatus(str, enum.Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class FiscalPeriod(Base):
    """A tenant's accounting period lock. Absence of a row means OPEN - only an
    explicitly CLOSED period blocks posting, so no one has to pre-create every
    month. Closing is a control, not a data migration: it stops back-dated
    entries into a reported period."""
    __tablename__ = "fin_fiscal_periods"
    __table_args__ = (
        UniqueConstraint("tenant_id", "fiscal_year", "fiscal_period",
                         name="uq_fin_period_tenant_year_period"),
    )

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)

    fiscal_year = Column(Integer, nullable=False)
    fiscal_period = Column(Integer, nullable=False)   # 1-12 calendar month
    status = Column(Enum(FiscalPeriodStatus), default=FiscalPeriodStatus.OPEN, nullable=False)

    closed_by = Column(String, nullable=True)
    closed_at = Column(DateTime(timezone=True), nullable=True)
    note = Column(String(256), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
