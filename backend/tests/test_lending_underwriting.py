"""Lending underwriting service: REAL fail-closed compliance gates + adverse
-action notice content. Uses the in-memory SQLite db fixture (conftest)."""
import uuid

import pytest

from app.lending.models.core import (LoanApplication, LoanStatus,
                                     UnderwritingDecision)
from app.lending.services.underwriting import (UnderwritingGateError,
                                               evaluate_policy,
                                               generate_adverse_action,
                                               underwrite_application)
from sqlalchemy import select

TENANT = "tenant_test"


def _uuid():
    return str(uuid.uuid4())


async def _mk_app(db, **over):
    base = dict(id=_uuid(), tenant_id=TENANT, application_number=f"LN-{uuid.uuid4().hex[:6]}",
                applicant_name="Test Applicant", product="personal_loan",
                credit_purpose="consumer", amount=18000, credit_score=740,
                annual_income=96000, dti_ratio=0.28, status=LoanStatus.RECEIVED.value)
    base.update(over)
    app = LoanApplication(**base)
    db.add(app)
    await db.commit()
    await db.refresh(app)
    return app


def test_evaluate_policy_denies_and_gives_specific_reasons():
    app = LoanApplication(tenant_id=TENANT, application_number="X", applicant_name="A",
                          amount=32000, credit_score=598, annual_income=41000, dti_ratio=0.58)
    verdict = evaluate_policy(app, None)
    assert verdict["decision"] == "DENY"
    assert verdict["reasons"]  # non-empty, specific
    assert all(len(r) >= 8 for r in verdict["reasons"])


def test_evaluate_policy_refers_on_missing_score():
    app = LoanApplication(tenant_id=TENANT, application_number="X", applicant_name="A",
                          amount=10000, credit_score=None, annual_income=90000, dti_ratio=0.2)
    # A missing hard input must NOT approve on absent data.
    assert evaluate_policy(app, None)["decision"] == "DENY"


@pytest.mark.asyncio
async def test_underwrite_approves_clean_application(db):
    app = await _mk_app(db)
    decision = await underwrite_application(
        db, TENANT, application_id=app.id, decided_by="uw@bank.example")
    assert decision.decision == "APPROVE"
    assert decision.apr is not None and decision.total_of_payments is not None
    refreshed = (await db.execute(select(LoanApplication).where(
        LoanApplication.id == app.id))).scalar_one()
    assert refreshed.status == LoanStatus.APPROVED.value


@pytest.mark.asyncio
async def test_underwrite_fails_closed_on_adverse_impact(db):
    """A fair-lending disparate-impact block must stop the decision: nothing persisted."""
    app = await _mk_app(db)
    adverse = {"race": {"white": {"selected": 80, "total": 100},
                        "black": {"selected": 30, "total": 100}}}
    with pytest.raises(UnderwritingGateError):
        await underwrite_application(
            db, TENANT, application_id=app.id, decided_by="uw@bank.example",
            approval_cohorts=adverse)
    # Fail-closed: no decision row persisted.
    rows = (await db.execute(select(UnderwritingDecision).where(
        UnderwritingDecision.application_id == app.id))).scalars().all()
    assert rows == []


@pytest.mark.asyncio
async def test_adverse_impact_ships_with_business_necessity(db):
    app = await _mk_app(db)
    adverse = {"race": {"white": {"selected": 80, "total": 100},
                        "black": {"selected": 30, "total": 100}}}
    decision = await underwrite_application(
        db, TENANT, application_id=app.id, decided_by="uw@bank.example",
        approval_cohorts=adverse,
        business_necessity=("Validated credit-risk model documented in the "
                            "fair-lending program with disparate-impact review."))
    assert decision.decision == "APPROVE"


@pytest.mark.asyncio
async def test_cross_tenant_application_is_not_found(db):
    app = await _mk_app(db)
    from app.lending.services.underwriting import ApplicationNotFound
    with pytest.raises(ApplicationNotFound):
        await underwrite_application(
            db, "other_tenant", application_id=app.id, decided_by="x")


@pytest.mark.asyncio
async def test_adverse_action_notice_has_specific_reasons(db):
    app = await _mk_app(db, credit_score=598, annual_income=41000, dti_ratio=0.58, amount=32000)
    decision = await underwrite_application(
        db, TENANT, application_id=app.id, decided_by="uw@bank.example")
    assert decision.decision == "DENY"

    notice = await generate_adverse_action(
        db, TENANT, application_id=app.id, decided_by="uw@bank.example")
    assert notice.specific_reasons  # non-empty, specific principal reasons
    assert notice.within_30_days is True
    assert "Equal Credit Opportunity Act" in notice.body
