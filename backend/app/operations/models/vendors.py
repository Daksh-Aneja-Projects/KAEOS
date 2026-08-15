"""
KAEOS Operations Domain — Vendor Models
"""
from sqlalchemy import Column, String, DateTime, ForeignKey, Float, Numeric, Date, Text
from sqlalchemy.sql import func
import uuid

from app.models.domain import Base

def _uuid():
    return str(uuid.uuid4())

class VendorContract(Base):
    """Subcontractor/Supplier operations agreements (distinct from Sales contracts)."""
    __tablename__ = "ops_vendor_contracts"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)

    vendor_name = Column(String(256), nullable=False)  # denormalized display / legacy
    # Roll ops vendor perf/risk up to the single finance master when resolvable.
    vendor_id = Column(String, ForeignKey("fin_vendors.id"), nullable=True, index=True)
    service_provided = Column(String(256), nullable=False) # e.g. "Cloud Hosting", "Facility Cleaning"
    
    contract_value = Column(Numeric(18, 2), default=0.00)
    renewal_date = Column(Date, nullable=True)
    
    owner_id = Column(String, ForeignKey("ops_team_members.id"), nullable=True)

    # VendorAgent's plain-English risk/renewal advisory. Deliberately separate
    # from any measured "risk_level" badge (that is derived from real
    # VendorPerformance scores, never stored here) — this is a labeled AI
    # opinion, not a metric.
    ai_recommendation = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

class VendorPerformance(Base):
    """Monthly rating sheets assessing supplier execution speed and cost efficiency."""
    __tablename__ = "ops_vendor_performance"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    vendor_contract_id = Column(String, ForeignKey("ops_vendor_contracts.id"), nullable=False, index=True)

    delivery_rating = Column(Float, default=100.00) # 0 to 100 score
    sla_compliance_score = Column(Float, default=100.00)
    overall_performance_score = Column(Float, default=100.00)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
