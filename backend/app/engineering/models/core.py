"""
KAEOS Engineering Domain — Core Models

Engineering + IT Ops is the largest slice of enterprise AI spend (coding ~55%,
IT ops ~10% of 2025 departmental spend per Menlo's enterprise survey), and it
was the one major function KAEOS did not model. These tables cover the service
catalog and the engineers who own it.
"""
from sqlalchemy import Column, String, DateTime, Enum, Text, Integer, Float, Boolean
from sqlalchemy.sql import func
import uuid
import enum

from app.models.domain import Base


def _uuid():
    return str(uuid.uuid4())


class ServiceTier(str, enum.Enum):
    TIER_1 = "TIER_1"   # revenue-critical, 24/7 on-call
    TIER_2 = "TIER_2"   # business-critical, business-hours
    TIER_3 = "TIER_3"   # internal / best-effort


class ServiceHealth(str, enum.Enum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    OUTAGE = "OUTAGE"
    MAINTENANCE = "MAINTENANCE"


class Engineer(Base):
    """An engineer in the delivery org (distinct from the HRIS record)."""
    __tablename__ = "eng_engineers"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)

    # Link to the canonical HR record when the person exists in the HRIS.
    hr_employee_id = Column(String, nullable=True, index=True)

    name = Column(String(128), nullable=False)
    email = Column(String(128), nullable=False)
    github_handle = Column(String(64), nullable=True)
    squad = Column(String(64), nullable=True)
    seniority = Column(String(32), nullable=True)  # JUNIOR | MID | SENIOR | STAFF | PRINCIPAL

    on_call = Column(Boolean, default=False)
    review_load = Column(Integer, default=0)  # open PRs awaiting this reviewer

    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Service(Base):
    """A deployable service in the catalog, with ownership and SLO posture."""
    __tablename__ = "eng_services"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)

    name = Column(String(128), nullable=False)
    slug = Column(String(64), nullable=False)
    description = Column(Text, nullable=True)
    repo_url = Column(String(256), nullable=True)

    tier = Column(Enum(ServiceTier), default=ServiceTier.TIER_2)
    health = Column(Enum(ServiceHealth), default=ServiceHealth.HEALTHY)

    owning_squad = Column(String(64), nullable=True)
    owner_engineer_id = Column(String, nullable=True, index=True)

    # SLO posture — the numbers an incident agent reasons over.
    slo_availability_target = Column(Float, default=99.9)   # percent
    slo_availability_actual = Column(Float, nullable=True)
    error_budget_remaining_pct = Column(Float, nullable=True)

    deploys_last_30d = Column(Integer, default=0)
    open_incidents = Column(Integer, default=0)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
