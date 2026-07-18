"""
KAEOS Sales Domain — Accounts Models
"""
from sqlalchemy import Column, String, DateTime, ForeignKey, Integer, Float, Text
from sqlalchemy.sql import func
import uuid

from app.models.domain import Base

def _uuid():
    return str(uuid.uuid4())

class Account(Base):
    """Customer organizations (mapped to accounts)."""
    __tablename__ = "sls_accounts"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)

    name = Column(String(256), nullable=False)
    website = Column(String(256), nullable=True)
    industry = Column(String(128), nullable=True)
    employee_count = Column(Integer, default=0)
    
    annual_recurring_revenue = Column(Float, default=0.00) # ARR
    health_score = Column(Float, default=1.00) # 0.00 to 1.00 Customer health
    assigned_rep_id = Column(String, ForeignKey("sls_reps.id"), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

class Contact(Base):
    """Contacts associated with customer accounts."""
    __tablename__ = "sls_contacts"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    account_id = Column(String, ForeignKey("sls_accounts.id"), nullable=False, index=True)

    first_name = Column(String(64), nullable=False)
    last_name = Column(String(64), nullable=False)
    email = Column(String(128), nullable=False)
    phone = Column(String(32), nullable=True)
    title = Column(String(128), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

class AccountActivity(Base):
    """Logs of interactions with contacts (emails, meetings, phone calls)."""
    __tablename__ = "sls_account_activities"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    account_id = Column(String, ForeignKey("sls_accounts.id"), nullable=False, index=True)

    activity_type = Column(String(32), nullable=False) # EMAIL, CALL, MEETING, TASK
    subject = Column(String(256), nullable=False)
    description = Column(Text, nullable=True)
    
    rep_id = Column(String, ForeignKey("sls_reps.id"), nullable=True)
    activity_date = Column(DateTime(timezone=True), server_default=func.now())

    created_at = Column(DateTime(timezone=True), server_default=func.now())
