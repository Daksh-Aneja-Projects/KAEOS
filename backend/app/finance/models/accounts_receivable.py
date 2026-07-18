"""
KAEOS Finance Domain — Accounts Receivable Models
Customer management, customer invoicing, and receipt/payment collection.
"""
from sqlalchemy import Column, String, Integer, Float, DateTime, Boolean, JSON, ForeignKey, Enum, Date, Text, Numeric
from sqlalchemy.sql import func
import uuid
import enum

from app.models.domain import Base

def _uuid():
    return str(uuid.uuid4())


class CustomerStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    PROSPECT = "PROSPECT"
    DELINQUENT = "DELINQUENT"
    COLLECTIONS = "COLLECTIONS"


class Customer(Base):
    """Customer / client master record for receivables."""
    __tablename__ = "fin_customers"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)

    customer_code = Column(String(32), nullable=False)
    name = Column(String(256), nullable=False)
    legal_name = Column(String(256), nullable=True)
    tax_id = Column(String(32), nullable=True)
    status = Column(Enum(CustomerStatus), default=CustomerStatus.ACTIVE)

    # Contact
    primary_contact = Column(String(128), nullable=True)
    email = Column(String(128), nullable=True)
    phone = Column(String(32), nullable=True)
    billing_address = Column(JSON, default=dict)

    # Credit terms
    credit_limit = Column(Numeric(18, 2), default=0)
    payment_terms_days = Column(Integer, default=30)
    currency = Column(String(3), default="USD")

    # AR metrics
    total_outstanding = Column(Numeric(18, 2), default=0)
    total_revenue_ytd = Column(Numeric(18, 2), default=0)
    days_sales_outstanding = Column(Float, nullable=True)
    ai_churn_risk = Column(Float, nullable=True)             # 0.0-1.0 AI-predicted

    # Aging buckets (auto-computed)
    aging_current = Column(Numeric(18, 2), default=0)
    aging_30 = Column(Numeric(18, 2), default=0)
    aging_60 = Column(Numeric(18, 2), default=0)
    aging_90 = Column(Numeric(18, 2), default=0)
    aging_over_90 = Column(Numeric(18, 2), default=0)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class CustomerInvoiceStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    SENT = "SENT"
    VIEWED = "VIEWED"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    OVERDUE = "OVERDUE"
    WRITE_OFF = "WRITE_OFF"
    VOIDED = "VOIDED"


class CustomerInvoice(Base):
    """Accounts Receivable invoice TO a customer."""
    __tablename__ = "fin_customer_invoices"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    customer_id = Column(String, ForeignKey("fin_customers.id"), nullable=False, index=True)

    invoice_number = Column(String(64), nullable=False, unique=True)
    invoice_date = Column(Date, nullable=False)
    due_date = Column(Date, nullable=False)
    status = Column(Enum(CustomerInvoiceStatus), default=CustomerInvoiceStatus.DRAFT)

    # Amounts
    subtotal = Column(Numeric(18, 2), nullable=False)
    tax_amount = Column(Numeric(18, 2), default=0)
    discount_amount = Column(Numeric(18, 2), default=0)
    total_amount = Column(Numeric(18, 2), nullable=False)
    amount_received = Column(Numeric(18, 2), default=0)
    balance_due = Column(Numeric(18, 2), nullable=False)
    currency = Column(String(3), default="USD")

    line_items = Column(JSON, default=list)

    # GL posting
    gl_account_id = Column(String, ForeignKey("fin_chart_of_accounts.id"), nullable=True)
    journal_entry_id = Column(String, ForeignKey("fin_journal_entries.id"), nullable=True)

    # Dunning
    dunning_level = Column(Integer, default=0)               # 0=none, 1=reminder, 2=warning, 3=final
    last_dunning_date = Column(Date, nullable=True)
    ai_payment_prediction_date = Column(Date, nullable=True) # AI-predicted payment date

    sent_at = Column(DateTime(timezone=True), nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Receipt(Base):
    """Payment received from a customer against an AR invoice."""
    __tablename__ = "fin_receipts"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    customer_id = Column(String, ForeignKey("fin_customers.id"), nullable=False, index=True)
    invoice_id = Column(String, ForeignKey("fin_customer_invoices.id"), nullable=False, index=True)

    receipt_number = Column(String(32), nullable=False)
    receipt_date = Column(Date, nullable=False)
    amount = Column(Numeric(18, 2), nullable=False)
    currency = Column(String(3), default="USD")
    method = Column(String(32), default="ACH")               # ACH, WIRE, CHECK, CREDIT_CARD

    reference_number = Column(String(64), nullable=True)
    bank_account_id = Column(String, ForeignKey("fin_bank_accounts.id"), nullable=True)
    journal_entry_id = Column(String, ForeignKey("fin_journal_entries.id"), nullable=True)

    # Reconciliation
    is_reconciled = Column(Boolean, default=False)
    reconciled_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
