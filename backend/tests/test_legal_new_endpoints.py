"""
10 legal models were seeded but had zero routes (HIGH gap): LegalTeamMember,
ContractTemplate, RegulatoryRequirement, ComplianceAssessment, Trademark,
TradeSecret, CaseEvent, CourtFiling, PrivacyImpactAssessment,
DataProcessingRecord (ROPA). This proves each new GET endpoint surfaces its
rows, tenant-scoped, and that /legal/matters now resolves the assigned
attorney to a human-readable name instead of a raw id.
"""
import uuid
from datetime import date

from app.legal.models.compliance import ComplianceAssessment, RegulatoryRequirement
from app.legal.models.contracts import ContractTemplate
from app.legal.models.core import LegalMatter, LegalTeamMember, MatterStatus
from app.legal.models.ip import IPStatus, Trademark, TradeSecret
from app.legal.models.litigation import Case, CaseEvent, CaseStage, CourtFiling
from app.legal.models.privacy import DataProcessingRecord, PrivacyImpactAssessment


def _t():
    return f"tenant_legal_ep_{uuid.uuid4().hex[:6]}"


async def _seed_all(db, tenant):
    team = LegalTeamMember(id=str(uuid.uuid4()), tenant_id=tenant, name="Test Attorney",
                           role="Attorney", email=f"{uuid.uuid4().hex[:6]}@test.io")
    tmpl = ContractTemplate(id=str(uuid.uuid4()), tenant_id=tenant, name="Test NDA",
                            contract_type="NDA", content="...")
    req = RegulatoryRequirement(id=str(uuid.uuid4()), tenant_id=tenant, regulation="GDPR",
                                section="Art 5", title="Data minimization")
    db.add_all([team, tmpl, req])
    await db.flush()

    assessment = ComplianceAssessment(id=str(uuid.uuid4()), tenant_id=tenant, framework="SOC2",
                                      assessment_date=date.today(), assessor="Auditor Co", score=90.0)
    case = Case(id=str(uuid.uuid4()), tenant_id=tenant, case_name="Test v. Case",
               stage=CaseStage.DISCOVERY, opposing_party="Case Corp")
    trademark = Trademark(id=str(uuid.uuid4()), tenant_id=tenant, mark_name="TESTMARK",
                          status=IPStatus.ACTIVE)
    secret = TradeSecret(id=str(uuid.uuid4()), tenant_id=tenant, asset_name="Test Secret")
    pia = PrivacyImpactAssessment(id=str(uuid.uuid4()), tenant_id=tenant, system_name="Test System")
    ropa = DataProcessingRecord(id=str(uuid.uuid4()), tenant_id=tenant, data_controller="Test Co",
                                purpose_of_processing="Testing")
    db.add_all([assessment, case, trademark, secret, pia, ropa])
    await db.flush()

    event = CaseEvent(id=str(uuid.uuid4()), tenant_id=tenant, case_id=case.id,
                      event_title="Test Hearing", event_date=date.today())
    filing = CourtFiling(id=str(uuid.uuid4()), tenant_id=tenant, case_id=case.id,
                         document_name="Test Filing", filing_date=date.today())
    db.add_all([event, filing])
    await db.commit()
    return {"case": case, "team": team}


async def test_new_list_endpoints_surface_seeded_rows(async_client, db):
    tenant = _t()
    ids = await _seed_all(db, tenant)
    h = {"X-Tenant-ID": tenant}

    r = await async_client.get("/api/v1/legal/team", headers=h)
    assert r.status_code == 200 and len(r.json()) == 1 and r.json()[0]["name"] == "Test Attorney"

    r = await async_client.get("/api/v1/legal/contract-templates", headers=h)
    assert r.status_code == 200 and len(r.json()) == 1 and r.json()[0]["name"] == "Test NDA"

    r = await async_client.get("/api/v1/legal/compliance/requirements", headers=h)
    assert r.status_code == 200 and len(r.json()) == 1 and r.json()[0]["regulation"] == "GDPR"

    r = await async_client.get("/api/v1/legal/compliance/assessments", headers=h)
    assert r.status_code == 200 and len(r.json()) == 1 and r.json()[0]["score"] == 90.0

    r = await async_client.get("/api/v1/legal/ip/trademarks", headers=h)
    assert r.status_code == 200 and len(r.json()) == 1 and r.json()[0]["mark_name"] == "TESTMARK"

    r = await async_client.get("/api/v1/legal/ip/trade-secrets", headers=h)
    assert r.status_code == 200 and len(r.json()) == 1 and r.json()[0]["asset_name"] == "Test Secret"

    r = await async_client.get("/api/v1/legal/privacy/pias", headers=h)
    assert r.status_code == 200 and len(r.json()) == 1 and r.json()[0]["system_name"] == "Test System"

    r = await async_client.get("/api/v1/legal/privacy/ropa", headers=h)
    assert r.status_code == 200 and len(r.json()) == 1 and r.json()[0]["data_controller"] == "Test Co"

    case_id = ids["case"].id
    r = await async_client.get(f"/api/v1/legal/cases/{case_id}/events", headers=h)
    assert r.status_code == 200 and len(r.json()) == 1 and r.json()[0]["title"] == "Test Hearing"

    r = await async_client.get(f"/api/v1/legal/cases/{case_id}/filings", headers=h)
    assert r.status_code == 200 and len(r.json()) == 1 and r.json()[0]["document_name"] == "Test Filing"


async def test_new_endpoints_are_tenant_scoped(async_client, db):
    tenant_a = _t()
    await _seed_all(db, tenant_a)
    tenant_b = _t()

    r = await async_client.get("/api/v1/legal/ip/trademarks", headers={"X-Tenant-ID": tenant_b})
    assert r.status_code == 200 and r.json() == []

    r = await async_client.get("/api/v1/legal/team", headers={"X-Tenant-ID": tenant_b})
    assert r.status_code == 200 and r.json() == []


async def test_matters_list_resolves_attorney_to_name_not_raw_id(async_client, db):
    tenant = _t()
    ids = await _seed_all(db, tenant)
    m = LegalMatter(id=str(uuid.uuid4()), tenant_id=tenant, title="Attorney-Assigned Matter",
                    matter_type="Corporate", status=MatterStatus.NEW,
                    assigned_attorney_id=ids["team"].id)
    db.add(m)
    await db.commit()

    r = await async_client.get("/api/v1/legal/matters", headers={"X-Tenant-ID": tenant})
    assert r.status_code == 200
    row = next(x for x in r.json() if x["id"] == m.id)
    assert row["assigned_attorney"] == "Test Attorney"
    assert "assigned_attorney_id" not in row  # never surface the raw id
