"""
KAEOS Lending - Loan Servicing Service

Amortization-schedule math, delinquency-bucket classification, and the REAL
fail-closed FDCPA gate for a debt-collection contact attempt. No contact ships
that fails the gate: the FDCPA checker runs here as a HARD gate (fail-closed)
- a blocking verdict raises before anything is persisted, mirroring
app.lending.services.underwriting's ECOA/FAIR_LENDING gate.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.compliance import run_checks
from app.lending.models.servicing import CollectionCase, CollectionCaseStatus, ServicedLoan
from app.lending.services.underwriting import LendingError
from app.services.provenance import append_ledger_event


class ServicingError(LendingError):
    pass


class LoanNotFound(ServicingError):
    pass


class CaseNotFound(ServicingError):
    pass


class CollectionGateError(ServicingError):
    """FDCPA blocked the contact attempt. Fail-closed: nothing was persisted."""

    def __init__(self, message: str, blocking: list):
        super().__init__(message)
        self.blocking = blocking


def delinquency_bucket(days_past_due: Optional[int]) -> str:
    """DPD -> the standard servicing delinquency bucket."""
    d = days_past_due or 0
    if d <= 0:
        return "current"
    if d < 30:
        return "1-29"
    if d < 60:
        return "30-59"
    if d < 90:
        return "60-89"
    return "90+"


def build_amortization_schedule(
    principal: Decimal, apr: Decimal, term_months: int, first_due: date,
) -> list[dict]:
    """A standard fixed-payment amortization schedule. Returns
    ``[{due_date, amount, principal, interest, status}]``, one row per
    installment, ``status`` always 'scheduled' (the caller marks paid/due/
    missed rows against the calendar)."""
    monthly_rate = (apr / Decimal("100")) / Decimal("12")
    n = max(1, int(term_months))
    if monthly_rate > 0:
        factor = (1 + monthly_rate) ** n
        payment = (principal * monthly_rate * factor) / (factor - 1)
    else:
        payment = principal / n
    payment = payment.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    schedule = []
    balance = principal
    due = first_due
    for i in range(n):
        interest = (balance * monthly_rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        principal_part = payment - interest
        if i == n - 1:
            # Last installment absorbs any rounding drift so the schedule
            # foots to exactly the original principal.
            principal_part = balance
            amount = principal_part + interest
        else:
            amount = payment
        balance = (balance - principal_part).quantize(Decimal("0.01"))
        schedule.append({
            "due_date": due.isoformat(),
            "amount": float(amount),
            "principal": float(principal_part),
            "interest": float(interest),
            "status": "scheduled",
        })
        due = _add_month(due)
    return schedule


def _add_month(d: date) -> date:
    month = d.month + 1
    year = d.year + (month - 1) // 12
    month = ((month - 1) % 12) + 1
    day = min(d.day, [31, 29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28,
                      31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1])
    return date(year, month, day)


async def load_collection_case(db: AsyncSession, tenant_id: str, case_id: str) -> CollectionCase:
    q = await db.execute(select(CollectionCase).where(
        CollectionCase.id == case_id, CollectionCase.tenant_id == tenant_id))
    case = q.scalar_one_or_none()
    if case is None:
        raise CaseNotFound(f"Collection case {case_id} not found")
    return case


def _days_since(dt: Optional[datetime], now: datetime) -> int:
    if dt is None:
        return 0
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return max(0, (now - dt).days)


async def attempt_collection_contact(
    db: AsyncSession,
    tenant_id: str,
    *,
    case_id: str,
    hour_local: int,
    channel: str = "phone",
    harassment: bool = False,
    notes: Optional[str] = None,
    actor: Optional[str] = None,
) -> CollectionCase:
    """Attempt one debt-collection contact through the REAL FDCPA gate and
    persist it. Fail-closed: a blocking verdict (out-of-window hour, a
    harassment flag, or a validation notice overdue past 5 days) raises
    ``CollectionGateError`` and NOTHING is persisted - the contact never
    happened as far as the system of record is concerned."""
    case = await load_collection_case(db, tenant_id, case_id)
    now = datetime.now(timezone.utc)

    collection_ctx = {
        "communications": [{"hour_local": hour_local}],
        "harassment": bool(harassment),
        "validation_notice_sent": bool(case.validation_notice_sent),
        "days_since_initial": _days_since(case.opened_at, now),
    }
    gate = run_checks(["FDCPA"], {"collection": collection_ctx})

    await append_ledger_event(
        db, tenant_id=tenant_id, event_type="COLLECTION_CONTACT_ATTEMPT",
        reasoning=(f"Collection contact attempt on case {case.id} via {channel} at "
                   f"{hour_local:02d}:00 local time; gate "
                   f"{'PASSED' if gate['verified'] else 'BLOCKED'} (FDCPA)."),
        evidence_ids=[case.id], scope=case.id, commit=False,
    )

    if not gate["verified"]:
        raise CollectionGateError(
            "Collection contact blocked by compliance gate(s): FDCPA.",
            blocking=gate["blocking"])

    entry = {
        "at": now.isoformat(), "hour_local": hour_local, "channel": channel,
        "harassment": bool(harassment), "notes": notes, "actor": actor,
    }
    log = list(case.contact_log or [])
    log.append(entry)
    case.contact_log = log
    case.last_contact_at = now
    if case.status == CollectionCaseStatus.OPEN.value:
        case.status = CollectionCaseStatus.IN_PROGRESS.value
    db.add(case)
    await db.commit()
    await db.refresh(case)
    return case
