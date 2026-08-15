"""Loan servicing + collections: amortization math, delinquency buckets, and
the REAL fail-closed FDCPA gate on a collection contact attempt (service
layer, in-memory SQLite db fixture - mirrors test_lending_underwriting.py).
Plus router-level coverage for the governed intake auto-call and the
admin-gated credit-policy endpoints."""
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.lending.models.servicing import (CollectionCase, CollectionCaseStatus,
                                          ServicedLoan, ServicingStatus)
from app.lending.services.servicing import (CaseNotFound, CollectionGateError,
                                            attempt_collection_contact,
                                            build_amortization_schedule,
                                            delinquency_bucket)
from app.services.auth import _create_token

TENANT = "tenant_test_servicing"


def _uuid():
    return str(uuid.uuid4())


def _ago(days):
    return datetime.now(timezone.utc) - timedelta(days=days)


async def _mk_case(db, *, validation_notice_sent=True, opened_ago=40, days_past_due=45) -> CollectionCase:
    loan = ServicedLoan(
        id=_uuid(), tenant_id=TENANT, loan_number=f"LN-{uuid.uuid4().hex[:6]}",
        product="personal_loan", borrower_name="Test Borrower",
        principal=Decimal("18000"), outstanding_principal=Decimal("15000"),
        apr=Decimal("12.5"), term_months=36, monthly_payment=Decimal("602.14"),
        payments_made=6, days_past_due=days_past_due,
        status=ServicingStatus.DELINQUENT.value, payment_schedule=[],
    )
    db.add(loan)
    await db.commit()
    await db.refresh(loan)

    case = CollectionCase(
        id=_uuid(), tenant_id=TENANT, serviced_loan_id=loan.id,
        status=CollectionCaseStatus.OPEN.value,
        delinquency_bucket=delinquency_bucket(days_past_due),
        validation_notice_sent=validation_notice_sent,
        validation_notice_sent_at=_ago(opened_ago - 1) if validation_notice_sent else None,
        contact_log=[], opened_at=_ago(opened_ago),
    )
    db.add(case)
    await db.commit()
    await db.refresh(case)
    return case


# ─── Pure functions ─────────────────────────────────────────────────────

def test_delinquency_bucket_boundaries():
    assert delinquency_bucket(0) == "current"
    assert delinquency_bucket(None) == "current"
    assert delinquency_bucket(1) == "1-29"
    assert delinquency_bucket(29) == "1-29"
    assert delinquency_bucket(30) == "30-59"
    assert delinquency_bucket(59) == "30-59"
    assert delinquency_bucket(60) == "60-89"
    assert delinquency_bucket(89) == "60-89"
    assert delinquency_bucket(90) == "90+"
    assert delinquency_bucket(400) == "90+"


def test_amortization_schedule_foots_to_principal():
    from datetime import date
    principal = Decimal("18000")
    schedule = build_amortization_schedule(principal, Decimal("12.5"), 36, date(2026, 1, 1))
    assert len(schedule) == 36
    total_principal = sum(Decimal(str(r["principal"])) for r in schedule)
    # Rounds to the cent over 36 installments.
    assert abs(total_principal - principal) < Decimal("0.05")
    assert schedule[0]["status"] == "scheduled"
    # Payment due dates step by calendar month.
    assert schedule[0]["due_date"] == "2026-01-01"
    assert schedule[1]["due_date"] == "2026-02-01"


# ─── FDCPA gate (fail-closed) ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_collection_contact_blocked_out_of_window(db):
    case = await _mk_case(db)
    with pytest.raises(CollectionGateError):
        await attempt_collection_contact(
            db, TENANT, case_id=case.id, hour_local=6, channel="phone", actor="collector@bank.example")
    # Fail-closed: nothing persisted.
    refreshed = (await db.execute(select(CollectionCase).where(
        CollectionCase.id == case.id))).scalar_one()
    assert refreshed.contact_log == []
    assert refreshed.status == CollectionCaseStatus.OPEN.value


@pytest.mark.asyncio
async def test_collection_contact_blocked_late_hour(db):
    case = await _mk_case(db)
    with pytest.raises(CollectionGateError):
        await attempt_collection_contact(
            db, TENANT, case_id=case.id, hour_local=22, channel="phone", actor="collector@bank.example")


@pytest.mark.asyncio
async def test_collection_contact_blocked_missing_validation_notice(db):
    case = await _mk_case(db, validation_notice_sent=False, opened_ago=10)
    with pytest.raises(CollectionGateError) as exc:
        await attempt_collection_contact(
            db, TENANT, case_id=case.id, hour_local=10, channel="phone", actor="collector@bank.example")
    codes = {b["framework"] for b in exc.value.blocking}
    assert "FDCPA" in codes


@pytest.mark.asyncio
async def test_collection_contact_passes_in_window(db):
    case = await _mk_case(db, validation_notice_sent=True, opened_ago=10)
    updated = await attempt_collection_contact(
        db, TENANT, case_id=case.id, hour_local=14, channel="phone",
        notes="Borrower reached, payment plan discussed.", actor="collector@bank.example")
    assert len(updated.contact_log) == 1
    assert updated.contact_log[0]["hour_local"] == 14
    assert updated.status == CollectionCaseStatus.IN_PROGRESS.value


@pytest.mark.asyncio
async def test_collection_contact_harassment_flag_blocks(db):
    case = await _mk_case(db)
    with pytest.raises(CollectionGateError):
        await attempt_collection_contact(
            db, TENANT, case_id=case.id, hour_local=11, channel="phone",
            harassment=True, actor="collector@bank.example")


@pytest.mark.asyncio
async def test_collection_contact_unknown_case_raises(db):
    with pytest.raises(CaseNotFound):
        await attempt_collection_contact(
            db, TENANT, case_id="does-not-exist", hour_local=10, actor="x")


# ─── Router: governed intake auto-call ──────────────────────────────────

@pytest.mark.asyncio
async def test_create_application_runs_governed_intake(async_client):
    r = await async_client.post(
        "/api/v1/lending/applications",
        headers={"X-Tenant-ID": "tenant_intake_probe"},
        json={
            "application_number": "LN-TEST-1", "applicant_name": "Test Applicant",
            "amount": 15000, "product": "personal_loan", "credit_score": 720,
            "annual_income": 90000, "dti_ratio": 0.25,
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    # IntakeAgent.validate_and_score ran automatically - the application is no
    # longer sitting un-triaged, and a real score (not a fabricated one) is set.
    assert body["intake_score"] is not None
    assert body["status"] == "IN_REVIEW"


@pytest.mark.asyncio
async def test_create_application_missing_fields_stays_received(async_client):
    r = await async_client.post(
        "/api/v1/lending/applications",
        headers={"X-Tenant-ID": "tenant_intake_probe2"},
        json={"application_number": "LN-TEST-2", "applicant_name": "", "amount": 15000},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    # Missing applicant_name -> intake finds it incomplete, status stays RECEIVED.
    assert body["status"] == "RECEIVED"
    assert body["intake_score"] is not None


# ─── Router: credit-policy admin surface ────────────────────────────────

@pytest.mark.asyncio
async def test_credit_policy_get_put_roundtrip(async_client):
    r = await async_client.put(
        "/api/v1/lending/credit-policies/personal_loan",
        headers={"X-Tenant-ID": "tenant_policy_probe"},
        json={"min_credit_score": 660, "max_dti_ratio": 0.4, "min_annual_income": 30000,
              "max_amount": 60000, "base_apr": 11.0},
    )
    assert r.status_code == 200, r.text
    saved = r.json()
    assert saved["min_credit_score"] == 660
    assert saved["max_amount"] == 60000

    got = await async_client.get(
        "/api/v1/lending/credit-policies", headers={"X-Tenant-ID": "tenant_policy_probe"})
    assert got.status_code == 200, got.text
    products = {p["product"]: p for p in got.json()}
    assert products["personal_loan"]["min_credit_score"] == 660

    # A different tenant's policy book is unaffected.
    other = await async_client.get(
        "/api/v1/lending/credit-policies", headers={"X-Tenant-ID": "tenant_policy_probe_other"})
    assert other.json() == []


@pytest.mark.asyncio
async def test_credit_policy_put_validates_range(async_client):
    r = await async_client.put(
        "/api/v1/lending/credit-policies/personal_loan",
        headers={"X-Tenant-ID": "tenant_policy_probe3"},
        json={"min_credit_score": 950, "max_dti_ratio": 0.4, "min_annual_income": 30000,
              "max_amount": 60000, "base_apr": 11.0},
    )
    assert r.status_code == 400, r.text


@pytest.mark.asyncio
async def test_credit_policy_put_rejected_for_non_admin(async_client):
    from app.core.config import get_settings
    settings = get_settings()
    prev = settings.DEV_MODE
    settings.DEV_MODE = False
    try:
        token = _create_token("u-view", "v@kaeos.ai", "VIEWER", "tenant_acme")
        r = await async_client.put(
            "/api/v1/lending/credit-policies/personal_loan",
            headers={"Authorization": f"Bearer {token}"},
            json={"min_credit_score": 660, "max_dti_ratio": 0.4, "min_annual_income": 30000,
                  "max_amount": 60000, "base_apr": 11.0},
        )
        assert r.status_code == 403, r.text
    finally:
        settings.DEV_MODE = prev
