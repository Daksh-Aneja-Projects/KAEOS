"""
Live enterprise twin cross-domain weave. See backend/app/services/reality_twin.py.

Healthcare, lending, and procurement used to get only their structural
backbone (Department/Capability/Agent/Process) - no headline entity was ever
woven in for them, unlike finance/sales/support/legal/engineering/operations.
"""
import pytest

from tests.conftest import TestingSessionLocal

T = "tenant_reality_twin_test"


async def _seed(db):
    from app.workforce.models.core import Department
    from app.healthcare.models.core import PatientEncounter
    from app.lending.models.core import LoanApplication
    from app.operations.models.procurement import ProcurementStatus, PurchaseRequest

    db.add(Department(id="d-hc", tenant_id=T, name="Healthcare", slug="healthcare", status="ACTIVE"))
    db.add(Department(id="d-ln", tenant_id=T, name="Lending & Credit", slug="lending", status="ACTIVE"))
    db.add(Department(id="d-pr", tenant_id=T, name="Procurement", slug="procurement", status="ACTIVE"))
    db.add(PatientEncounter(
        tenant_id=T, encounter_number="ENC-1", patient_ref="pt-anon-1",
        encounter_type="office_visit", status="OPEN",
    ))
    db.add(LoanApplication(
        tenant_id=T, application_number="APP-1", applicant_name="Jordan Lee",
        amount=15000,
    ))
    db.add(PurchaseRequest(
        tenant_id=T, item_description="Laptops for onboarding cohort",
        status=ProcurementStatus.PENDING_APPROVAL,
    ))
    await db.commit()


@pytest.mark.asyncio
async def test_twin_weaves_healthcare_lending_procurement_headline_entities(db, monkeypatch):
    # build_live_twin opens its own session via app.core.database.AsyncSessionLocal
    # (not the request-scoped `db` dependency) - point it at the same in-memory
    # test database the `db` fixture writes to.
    import app.services.reality_twin as reality_twin
    monkeypatch.setattr(reality_twin, "AsyncSessionLocal", TestingSessionLocal)

    await _seed(db)
    nodes, edges = await reality_twin.build_live_twin(T)

    by_label = {}
    for n in nodes.values():
        by_label.setdefault(n["label"], []).append(n)

    assert "Encounter" in by_label, "healthcare got no headline entity woven into the twin"
    assert "LoanApplication" in by_label, "lending got no headline entity woven into the twin"
    assert "Requisition" in by_label, "procurement got no headline entity woven into the twin"

    encounter = by_label["Encounter"][0]
    assert "ENC-1" in encounter["name"]
    assert any(e["source"] == "d-hc" and e["target"] == encounter["id"] and e["type"] == "TREATS"
              for e in edges)

    loan = by_label["LoanApplication"][0]
    assert loan["name"] == "Jordan Lee"
    assert any(e["source"] == "d-ln" and e["target"] == loan["id"] and e["type"] == "UNDERWRITES"
              for e in edges)

    requisition = by_label["Requisition"][0]
    assert requisition["name"] == "Laptops for onboarding cohort"
    assert any(e["source"] == "d-pr" and e["target"] == requisition["id"] and e["type"] == "REQUESTS"
              for e in edges)


@pytest.mark.asyncio
async def test_twin_survives_a_missing_department_for_a_new_domain(db, monkeypatch):
    """Same defensive contract as the other 6 _weave() calls: no lending
    department at all must not crash the twin build, just skip that weave."""
    import app.services.reality_twin as reality_twin
    from app.lending.models.core import LoanApplication

    monkeypatch.setattr(reality_twin, "AsyncSessionLocal", TestingSessionLocal)

    db.add(LoanApplication(
        tenant_id=T, application_number="APP-2", applicant_name="No Department Yet", amount=500,
    ))
    await db.commit()

    nodes, edges = await reality_twin.build_live_twin(T)
    assert not any(n["label"] == "LoanApplication" for n in nodes.values())


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
