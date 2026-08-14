"""
Entitlement + billing models (theme M).

Open-core + managed cloud: the platform is fully usable self-hosted with NO
billing wired. These tables only matter in managed-cloud mode
(KAEOS_MANAGED_CLOUD=true) where plan entitlements are enforced and metered
usage is rated + optionally pushed to Stripe.

Money is Decimal (Numeric) everywhere — never float.
"""
from sqlalchemy import (
    Boolean, Column, Date, DateTime, Integer, Numeric, String, UniqueConstraint, Index,
)
from sqlalchemy.sql import func
import uuid

from app.models.domain import Base


def _uuid():
    return str(uuid.uuid4())


class BillingAccount(Base):
    """Per-tenant Stripe linkage + seat count. The plan itself lives on
    Tenant.plan; this row only holds the managed-cloud billing identifiers so a
    self-host install never needs it."""
    __tablename__ = "billing_accounts"

    tenant_id = Column(String, primary_key=True)
    seats = Column(Integer, nullable=False, default=1)
    stripe_customer_id = Column(String, nullable=True)
    stripe_subscription_id = Column(String, nullable=True)
    # The metered subscription item usage records are pushed against.
    stripe_meter_item_id = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class UsageMeterReport(Base):
    """One rating rollup per (tenant, billing period). Persisted by the metering
    job so the Stripe push is idempotent: re-running a period upserts this row
    and reports the same total with action=set, never double-counting."""
    __tablename__ = "usage_meter_reports"
    __table_args__ = (
        UniqueConstraint("tenant_id", "period_start", name="uq_usage_report_period"),
        Index("ix_usage_report_tenant_period", "tenant_id", "period_start"),
    )

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    period_start = Column(Date, nullable=False)          # first day of the month
    metered_executions = Column(Integer, nullable=False, default=0)
    included_allowance = Column(Integer, nullable=False, default=0)
    overage_units = Column(Integer, nullable=False, default=0)
    stripe_status = Column(String(32), nullable=False, default="pending")  # reported|noop|error|pending
    stripe_usage_record_id = Column(String, nullable=True)
    reported_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class SkillValueBaseline(Base):
    """Per-skill human baseline for the ROI 'value delivered' figure. Without a
    baseline the ROI tile stays null-with-note — KAEOS never invents a dollar
    value. baseline_minutes = how long the same task takes a person;
    loaded_hourly_rate_usd = their fully-loaded cost."""
    __tablename__ = "skill_value_baselines"
    __table_args__ = (
        UniqueConstraint("tenant_id", "skill_id_name", name="uq_skill_baseline"),
    )

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    skill_id_name = Column(String, nullable=False)
    baseline_minutes = Column(Integer, nullable=False, default=0)
    loaded_hourly_rate_usd = Column(Numeric(12, 2), nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class StripeWebhookEvent(Base):
    """Idempotency ledger for inbound Stripe webhooks. GLOBAL (no tenant_id):
    Stripe events are not tenant-scoped and the webhook has no tenant session.
    event_id is Stripe's evt_… id, so a redelivered event is a no-op."""
    __tablename__ = "stripe_webhook_events"

    event_id = Column(String, primary_key=True)          # Stripe evt_… id
    event_type = Column(String(64), nullable=False)
    received_at = Column(DateTime(timezone=True), server_default=func.now())
    processed = Column(Boolean, nullable=False, default=False)
