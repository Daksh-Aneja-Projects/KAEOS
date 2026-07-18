"""
KAEOS Finance Domain — Accounts Payable Models
Vendor management, invoice processing, and payment tracking.
"""
from sqlalchemy import Column, String, Integer, Float, DateTime, Boolean, JSON, ForeignKey, Enum, Date, Text, Numeric
from sqlalchemy.sql import func
import uuid
import enum

from app.models.domain import Base

def _uuid():
    return str(uuid.uuid4())


class VendorStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    BLOCKED = "BLOCKED"
    ON_HOLD = "ON_HOLD"


class Vendor(Base):
    """Supplier / vendor master record."""
    __tablename__ = "fin_vendors"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)

    vendor_code = Column(String(32), nullable=False)
    name = Column(String(256), nullable=False)
    legal_name = Column(String(256), nullable=True)
    tax_id = Column(String(32), nullable=True)              # EIN / VAT number
    status = Column(Enum(VendorStatus), default=VendorStatus.ACTIVE)

    # Contact
    primary_contact = Column(String(128), nullable=True)
    email = Column(String(128), nullable=True)
    phone = Column(String(32), nullable=True)
    website = Column(String(256), nullable=True)

    # Address
    address_line1 = Column(String(256), nullable=True)
    address_line2 = Column(String(256), nullable=True)
    city = Column(String(64), nullable=True)
    state = Column(String(64), nullable=True)
    postal_code = Column(String(16), nullable=True)
    country = Column(String(3), default="USA")              # ISO 3166-1 alpha-3

    # Payment terms
    payment_terms_days = Column(Integer, default=30)         # Net 30, Net 60, etc.
    default_gl_account_id = Column(String, ForeignKey("fin_chart_of_accounts.id"), nullable=True)
    currency = Column(String(3), default="USD")
    bank_account_number = Column(String(64), nullable=True)
    bank_routing_number = Column(String(32), nullable=True)

    # Compliance
    w9_on_file = Column(Boolean, default=False)
    insurance_verified = Column(Boolean, default=False)
    risk_level = Column(String(16), default="LOW")           # LOW, MEDIUM, HIGH

    # Performance
    performance_score = Column(Float, nullable=True)         # 0-100 AI-computed
    total_spend_ytd = Column(Numeric(18, 2), default=0)
    total_invoices_ytd = Column(Integer, default=0)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class InvoiceStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    OVERDUE = "OVERDUE"
    DISPUTED = "DISPUTED"
    VOIDED = "VOIDED"


class Invoice(Base):
    """Accounts Payable invoice from a vendor."""
    __tablename__ = "fin_invoices"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    vendor_id = Column(String, ForeignKey("fin_vendors.id"), nullable=False, index=True)

    invoice_number = Column(String(64), nullable=False)
    po_number = Column(String(64), nullable=True)            # Purchase Order reference
    invoice_date = Column(Date, nullable=False)
    due_date = Column(Date, nullable=False)
    received_date = Column(Date, nullable=True)

    status = Column(Enum(InvoiceStatus), default=InvoiceStatus.DRAFT)

    # Amounts
    subtotal = Column(Numeric(18, 2), nullable=False)
    tax_amount = Column(Numeric(18, 2), default=0)
    shipping_amount = Column(Numeric(18, 2), default=0)
    discount_amount = Column(Numeric(18, 2), default=0)
    total_amount = Column(Numeric(18, 2), nullable=False)
    amount_paid = Column(Numeric(18, 2), default=0)
    balance_due = Column(Numeric(18, 2), nullable=False)
    currency = Column(String(3), default="USD")

    # Line items stored as JSON for flexibility
    line_items = Column(JSON, default=list)                  # [{description, qty, unit_price, gl_account, amount}]

    # GL posting
    gl_account_id = Column(String, ForeignKey("fin_chart_of_accounts.id"), nullable=True)
    journal_entry_id = Column(String, ForeignKey("fin_journal_entries.id"), nullable=True)

    # 3-Way Matching (PO ↔ Receipt ↔ Invoice)
    three_way_match_status = Column(String(16), default="PENDING")  # PENDING, MATCHED, EXCEPTION
    receipt_matched = Column(Boolean, default=False)
    po_matched = Column(Boolean, default=False)

    # AI-assisted
    ai_categorized = Column(Boolean, default=False)
    ai_confidence = Column(Float, nullable=True)
    ai_duplicate_flag = Column(Boolean, default=False)

    # Approval
    approved_by = Column(String, nullable=True)
    approved_at = Column(DateTime(timezone=True), nullable=True)

    # Attachments
    attachment_paths = Column(JSON, default=list)            # GCS/S3 URIs for scanned invoices

    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class PaymentMethod(str, enum.Enum):
    ACH = "ACH"
    WIRE = "WIRE"
    CHECK = "CHECK"
    CREDIT_CARD = "CREDIT_CARD"
    VIRTUAL_CARD = "VIRTUAL_CARD"


class PaymentStatus(str, enum.Enum):
    SCHEDULED = "SCHEDULED"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    REVERSED = "REVERSED"
    VOIDED = "VOIDED"


class Payment(Base):
    """Payment against an AP invoice."""
    __tablename__ = "fin_payments"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    vendor_id = Column(String, ForeignKey("fin_vendors.id"), nullable=False, index=True)
    invoice_id = Column(String, ForeignKey("fin_invoices.id"), nullable=False, index=True)

    payment_number = Column(String(32), nullable=False)
    payment_date = Column(Date, nullable=False)
    amount = Column(Numeric(18, 2), nullable=False)
    currency = Column(String(3), default="USD")
    method = Column(Enum(PaymentMethod), default=PaymentMethod.ACH)
    status = Column(Enum(PaymentStatus), default=PaymentStatus.SCHEDULED)

    # Bank details
    bank_account_id = Column(String, ForeignKey("fin_bank_accounts.id"), nullable=True)
    reference_number = Column(String(64), nullable=True)     # Check # or wire ref
    confirmation_number = Column(String(64), nullable=True)

    # GL posting
    journal_entry_id = Column(String, ForeignKey("fin_journal_entries.id"), nullable=True)

    # Discount captured
    discount_taken = Column(Numeric(18, 2), default=0)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
