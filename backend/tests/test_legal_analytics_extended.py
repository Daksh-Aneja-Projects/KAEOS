"""legal_analytics() used to be contracts-only. This proves it now also
computes obligation overdue rate, DSAR SLA risk, and litigation exposure by
stage from real tenant rows (never a fabricated value)."""
import uuid
from datetime import date, timedelta

from app.legal.models.compliance import ComplianceObligation, ObligationStatus
from app.legal.models.litigation import Case, CaseStage
from app.legal.models.privacy import DataSubjectRequest, DsarStatus, DsarType
from app.legal.services.analytics import legal_analytics


def _t():
    return f"tenant_legal_an_{uuid.uuid4().hex[:6]}"


def _kpi(payload, key):
    return next(k for k in payload["kpis"] if k["key"] == key)


async def test_obligation_overdue_rate_is_null_with_no_obligations(db):
    tenant = _t()
    payload = await legal_analytics(db, tenant)
    assert _kpi(payload, "obligation_overdue_rate")["value"] is None  # honesty: never fake 0%


async def test_obligation_overdue_rate_computed_from_real_rows(db):
    tenant = _t()
    db.add_all([
        ComplianceObligation(id=str(uuid.uuid4()), tenant_id=tenant, title="A", status=ObligationStatus.OVERDUE),
        ComplianceObligation(id=str(uuid.uuid4()), tenant_id=tenant, title="B", status=ObligationStatus.OVERDUE),
        ComplianceObligation(id=str(uuid.uuid4()), tenant_id=tenant, title="C", status=ObligationStatus.PENDING),
        ComplianceObligation(id=str(uuid.uuid4()), tenant_id=tenant, title="D", status=ObligationStatus.COMPLETED),
    ])
    await db.commit()

    payload = await legal_analytics(db, tenant)
    assert _kpi(payload, "obligation_overdue_rate")["value"] == 50.0


async def test_dsar_at_risk_counts_near_deadline_non_terminal_requests(db):
    tenant = _t()
    db.add_all([
        DataSubjectRequest(id=str(uuid.uuid4()), tenant_id=tenant, requestor_name="X",
                           requestor_email="x@test.io", request_type=DsarType.ACCESS,
                           status=DsarStatus.RECEIVED, request_date=date.today(),
                           deadline_date=date.today() + timedelta(days=2)),  # at risk
        DataSubjectRequest(id=str(uuid.uuid4()), tenant_id=tenant, requestor_name="Y",
                           requestor_email="y@test.io", request_type=DsarType.ACCESS,
                           status=DsarStatus.RECEIVED, request_date=date.today(),
                           deadline_date=date.today() + timedelta(days=25)),  # not yet at risk
        DataSubjectRequest(id=str(uuid.uuid4()), tenant_id=tenant, requestor_name="Z",
                           requestor_email="z@test.io", request_type=DsarType.ACCESS,
                           status=DsarStatus.COMPLETED, request_date=date.today() - timedelta(days=5),
                           deadline_date=date.today() + timedelta(days=1)),  # terminal, excluded
    ])
    await db.commit()

    payload = await legal_analytics(db, tenant)
    assert _kpi(payload, "dsar_at_risk")["value"] == 1


async def test_litigation_exposure_by_stage_chart(db):
    tenant = _t()
    db.add_all([
        Case(id=str(uuid.uuid4()), tenant_id=tenant, case_name="A", stage=CaseStage.DISCOVERY,
            exposure_amount=100000, opposing_party="Opp A"),
        Case(id=str(uuid.uuid4()), tenant_id=tenant, case_name="B", stage=CaseStage.TRIAL,
            exposure_amount=250000, opposing_party="Opp B"),
    ])
    await db.commit()

    payload = await legal_analytics(db, tenant)
    chart = next(c for c in payload["charts"] if c["key"] == "exposure_by_stage")
    by_label = {i["label"]: i["value"] for i in chart["items"]}
    assert by_label["DISCOVERY"] == 100000.0
    assert by_label["TRIAL"] == 250000.0
    assert _kpi(payload, "litigation_exposure")["value"] == 350000.0
