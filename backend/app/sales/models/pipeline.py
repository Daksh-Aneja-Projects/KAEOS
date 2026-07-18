"""
KAEOS Sales Domain — Pipeline Models
"""
from sqlalchemy import Column, String, DateTime, Enum, ForeignKey, Numeric, Float, Date, Integer
from sqlalchemy.sql import func
import uuid
import enum

from app.models.domain import Base

def _uuid():
    return str(uuid.uuid4())

class OpportunityStage(str, enum.Enum):
    PROSPECTING = "PROSPECTING"
    QUALIFICATION = "QUALIFICATION"
    PROPOSAL = "PROPOSAL"
    NEGOTIATION = "NEGOTIATION"
    CLOSED_WON = "CLOSED_WON"
    CLOSED_LOST = "CLOSED_LOST"

class Opportunity(Base):
    """Sales opportunities / deals in the pipeline."""
    __tablename__ = "sls_opportunities"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)

    name = Column(String(256), nullable=False)
    account_id = Column(String, nullable=True) # Linked customer/account reference
    
    stage = Column(Enum(OpportunityStage), default=OpportunityStage.PROSPECTING)
    amount = Column(Numeric(18, 2), default=0)
    probability = Column(Float, default=10.00) # 0 to 100 percentage
    
    close_date = Column(Date, nullable=True)
    assigned_rep_id = Column(String, ForeignKey("sls_reps.id"), nullable=True)
    
    # AI insights
    ai_win_probability = Column(Float, nullable=True)
    ai_stalled_flag = Column(Enum(OpportunityStage), nullable=True) # Used for stage alerts or ignored
    ai_next_step = Column(String(512), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

class OpportunityProduct(Base):
    """Products attached to opportunities."""
    __tablename__ = "sls_opportunity_products"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    opportunity_id = Column(String, ForeignKey("sls_opportunities.id"), nullable=False, index=True)

    product_name = Column(String(128), nullable=False)
    quantity = Column(Integer, default=1) if 'Integer' in globals() else Column(String(32), default="1") # Let's verify Integer is imported.
    unit_price = Column(Numeric(18, 2), default=0)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
