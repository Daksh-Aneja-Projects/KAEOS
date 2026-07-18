"""
KAEOS Operations Domain — Procurement Models
"""
from sqlalchemy import Column, String, DateTime, Enum, ForeignKey, Integer, Numeric, Boolean
from sqlalchemy.sql import func
import uuid
import enum

from app.models.domain import Base

def _uuid():
    return str(uuid.uuid4())

class ProcurementStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    ORDERED = "ORDERED"
    RECEIVED = "RECEIVED"
    CANCELLED = "CANCELLED"

class PurchaseRequest(Base):
    """Internal purchase claims submitted by employees before PO issue."""
    __tablename__ = "ops_purchase_requests"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)

    item_description = Column(String(256), nullable=False)
    quantity = Column(Integer, default=1)
    unit_price = Column(Numeric(18, 2), default=0.00)
    
    total_estimated_cost = Column(Numeric(18, 2), default=0.00)
    status = Column(Enum(ProcurementStatus), default=ProcurementStatus.DRAFT)
    
    requested_by = Column(String(128), nullable=True) # Employee ID/Name
    department = Column(String(64), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

class PurchaseOrder(Base):
    """Official POs sent to suppliers."""
    __tablename__ = "ops_purchase_orders"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    purchase_request_id = Column(String, ForeignKey("ops_purchase_requests.id"), nullable=True)

    po_number = Column(String(32), nullable=False, unique=True)
    vendor_name = Column(String(256), nullable=False)
    total_amount = Column(Numeric(18, 2), default=0.00)
    status = Column(Enum(ProcurementStatus), default=ProcurementStatus.PENDING_APPROVAL)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

class GoodsReceipt(Base):
    """Delivery confirmation checklist logs validating purchase receipt."""
    __tablename__ = "ops_goods_receipts"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    purchase_order_id = Column(String, ForeignKey("ops_purchase_orders.id"), nullable=False, index=True)

    receiver_name = Column(String(128), nullable=False)
    received_quantity = Column(Integer, default=1)
    is_damaged = Column(Boolean, default=False)
    status = Column(String(32), default="SUCCESS")

    created_at = Column(DateTime(timezone=True), server_default=func.now())
