"""
The healthcare compliance-report model/endpoint and the EHR FHIR connector -
previously absent (healthcare had no persisted compliance-report surface and
no connector code behind packs/healthcare.yaml's 'ehr' integration claim).
"""
import pytest

from app.healthcare.connectors.ehr_sync import EHRSyncConnector


def test_ehr_connector_rejects_unsupported_provider():
    with pytest.raises(ValueError):
        EHRSyncConnector("tenant_x", "meditech", {"fhir_base_url": "https://x", "access_token": "t"})


def test_ehr_connector_requires_base_url():
    with pytest.raises(ValueError):
        EHRSyncConnector("tenant_x", "epic", {"access_token": "t"})


def test_ehr_connector_requires_access_token():
    with pytest.raises(ValueError):
        EHRSyncConnector("tenant_x", "epic", {"fhir_base_url": "https://epic.example.com/fhir"})


def test_ehr_connector_builds_base_url_and_headers():
    conn = EHRSyncConnector("tenant_x", "Epic", {
        "fhir_base_url": "https://epic.example.com/fhir/", "access_token": "tok123",
    })
    # Provider name normalized, trailing slash stripped, bearer header built.
    assert conn.provider == "epic"
    assert conn.base_url == "https://epic.example.com/fhir"
    assert conn.headers["Authorization"] == "Bearer tok123"
    assert conn.headers["Accept"] == "application/fhir+json"


@pytest.mark.asyncio
async def test_compliance_reports_endpoint_returns_persisted_report(async_client, db):
    from app.healthcare.models.compliance import ComplianceReport

    db.add(ComplianceReport(
        tenant_id="tenant_acme", framework="HIPAA", report_name="Test HIPAA Report",
        period_year=2026, status="GENERATED", data={"summary": "All clear."},
    ))
    await db.commit()

    r = await async_client.get("/api/v1/healthcare/compliance-reports")
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body) == 1
    assert body[0]["framework"] == "HIPAA"
    assert body[0]["report_name"] == "Test HIPAA Report"
    assert body[0]["data"]["summary"] == "All clear."


@pytest.mark.asyncio
async def test_compliance_reports_endpoint_is_tenant_scoped(async_client, db):
    from app.healthcare.models.compliance import ComplianceReport

    db.add(ComplianceReport(
        tenant_id="tenant_other", framework="HIPAA", report_name="Other tenant's report",
        period_year=2026, status="GENERATED", data={},
    ))
    await db.commit()

    r = await async_client.get("/api/v1/healthcare/compliance-reports")
    assert r.status_code == 200, r.text
    assert r.json() == []
