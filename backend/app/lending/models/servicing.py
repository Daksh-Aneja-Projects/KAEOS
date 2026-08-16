"""
KAEOS Lending Domain - Loan Servicing Models

Once a credit decision is APPROVED and a loan is funded, control shifts from
underwriting to servicing: an amortizing payment schedule, real delinquency
tracking, and - for a loan more than 30 days past due - a collections case
whose contact activity is governed by FDCPA (15 USC 1692c/1692d/1692g). This
is the exact context app.compliance.checkers.lending.check_fdcpa reads
(``context['collection']``); nothing in the platform built a caller for it
until now, so the checker was wired to an advertised compliance framework
with no real feature behind it.
"""
from __future__ import annotations

import enum
import uuid

from sqlalchemy import (Boolean, Column, Date, DateTime, ForeignKey, Integer,
                        JSON, Numeric, String, UniqueConstraint)
from sqlalchemy.sql import func

from app.models.domain import Base
from app.models.mixins import LegalHoldMixin


def _uuid():
    return str(uuid.uuid4())


class ServicingStatus(str, enum.Enum):
    CURRENT = "CURRENT"
    DELINQUENT = "DELINQUENT"
    DEFAULT = "DEFAULT"
    PAID_OFF = "PAID_OFF"


class CollectionCaseStatus(str, enum.Enum):
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    RESOLVED = "RESOLVED"
    ESCALATED = "ESCALATED"


class ServicedLoan(Base, LegalHoldMixin):
    """A funded loan under active servicing. ``payment_schedule`` is the full
    amortization schedule (one JSON row per installment) so the servicing team
    can see exactly what is due and what has posted, without a separate
    ledger table for a demo-scale schedule."""
    __tablename__ = "lnd_serviced_loans"
    __table_args__ = (
        UniqueConstraint("tenant_id", "loan_number", name="uq_lnd_serviced_loan_tenant_number"),
    )

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    application_id = Column(String, ForeignKey("lnd_loan_applications.id"), nullable=True, index=True)

    loan_number = Column(String(32), nullable=False)
    product = Column(String(48), nullable=False, default="personal_loan")
    borrower_name = Column(String(160), nullable=False)

    principal = Column(Numeric(18, 2), nullable=False)
    outstanding_principal = Column(Numeric(18, 2), nullable=False)
    apr = Column(Numeric(9, 4), nullable=False)
    term_months = Column(Integer, nullable=False)
    monthly_payment = Column(Numeric(18, 2), nullable=False)

    next_due_date = Column(Date, nullable=True)
    last_payment_date = Column(Date, nullable=True)
    last_payment_amount = Column(Numeric(18, 2), nullable=True)
    payments_made = Column(Integer, nullable=False, default=0)
    days_past_due = Column(Integer, nullable=False, default=0)

    status = Column(String(16), nullable=False, default=ServicingStatus.CURRENT.value)
    # [{due_date, amount, principal, interest, status}], status one of paid|due|scheduled|missed.
    payment_schedule = Column(JSON, default=list)

    funded_at = Column(DateTime(timezone=True), server_default=func.now())
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class CollectionCase(Base, LegalHoldMixin):
    """A collections case opened once a serviced loan is delinquent. The
    contact log is an append-only record of every collection communication -
    exactly the shape app.compliance.checkers.lending.check_fdcpa reads
    (``hour_local`` per communication, a harassment flag, validation-notice
    timing). A contact attempt is appended only after it clears the FDCPA
    gate (see app.lending.services.servicing.attempt_collection_contact); a
    blocked attempt is never persisted here, matching the fail-closed pattern
    the underwriting gates use."""
    __tablename__ = "lnd_collection_cases"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    serviced_loan_id = Column(String, ForeignKey("lnd_serviced_loans.id"), nullable=False, index=True)

    status = Column(String(16), nullable=False, default=CollectionCaseStatus.OPEN.value)
    delinquency_bucket = Column(String(16), nullable=False, default="1-29")

    validation_notice_sent = Column(Boolean, nullable=False, default=False)
    validation_notice_sent_at = Column(DateTime(timezone=True), nullable=True)

    # [{at, hour_local, channel, harassment, notes, actor}]
    contact_log = Column(JSON, default=list)
    last_contact_at = Column(DateTime(timezone=True), nullable=True)

    opened_at = Column(DateTime(timezone=True), server_default=func.now())
    closed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
