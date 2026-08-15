"""
The healthcare agent-trigger endpoints (previously nonexistent - the agents
were dead code with no route). Exercised over the real HTTP endpoints, as
tests/test_domain_workflows.py does for the other domains' workflow routes.
"""
import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.healthcare.models.core import ClinicalTask, PatientEncounter, PHIDisclosure

TENANT = "tenant_acme"  # dev-context tenant resolved for unauthenticated tests


@pytest.fixture(autouse=True)
def _stub_hitl_and_fairness(monkeypatch):
    """See tests/test_healthcare_agent_gates.py for why: the real HITL/fairness
    paths open their own session against a DB the in-memory test fixture never
    provisions; these tests are about the new routes, not that infrastructure."""
    from app.services.fairness_engine import FairnessEngine
    from app.services.hitl_manager import hitl_manager as _hitl

    async def _fake_confirm(skill, context):
        return {"pending": True, "execution_id": context.get("execution_id", "test-exec")}

    monkeypatch.setattr(_hitl, "request_human_confirmation", _fake_confirm)
    monkeypatch.setattr(FairnessEngine, "requires_fairness_check", lambda self, skill, context: False)


async def _seed_encounter(db, **overrides) -> PatientEncounter:
    kw = {
        "encounter_number": "ENC-R-1", "patient_ref": "pt-anon-r1",
        "encounter_type": "office_visit", "status": "OPEN", "reason": "severe laceration",
    }
    kw.update(overrides)
    enc = PatientEncounter(tenant_id=TENANT, **kw)
    db.add(enc)
    await db.commit()
    await db.refresh(enc)
    return enc


@pytest.mark.asyncio
async def test_triage_route_transitions_and_returns_priority(async_client: AsyncClient, db):
    enc = await _seed_encounter(db)
    r = await async_client.post(f"/api/v1/healthcare/encounters/{enc.id}/triage")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["priority"] == "URGENT"
    assert body["status"] == "PENDING_HITL"

    await db.refresh(enc)
    assert enc.status == "TRIAGED"


@pytest.mark.asyncio
async def test_triage_route_404_on_unknown_encounter(async_client: AsyncClient):
    r = await async_client.post("/api/v1/healthcare/encounters/does-not-exist/triage")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_triage_route_409_on_already_triaged_encounter(async_client: AsyncClient, db):
    enc = await _seed_encounter(db, encounter_number="ENC-R-1B", status="TRIAGED")
    r = await async_client.post(f"/api/v1/healthcare/encounters/{enc.id}/triage")
    assert r.status_code == 409, r.text


@pytest.mark.asyncio
async def test_suggest_codes_route_creates_task(async_client: AsyncClient, db):
    enc = await _seed_encounter(db, encounter_number="ENC-R-2", reason="wellness visit")
    r = await async_client.post(f"/api/v1/healthcare/encounters/{enc.id}/suggest-codes")
    assert r.status_code == 200, r.text
    body = r.json()
    task = (await db.execute(select(ClinicalTask).where(
        ClinicalTask.id == body["task_id"]))).scalar_one()
    assert task.status == "IN_PROGRESS"
    assert task.task_type == "coding"


@pytest.mark.asyncio
async def test_prior_auth_route_creates_task_with_procedure_and_payer(async_client: AsyncClient, db):
    enc = await _seed_encounter(db, encounter_number="ENC-R-3", reason="chronic low back pain")
    r = await async_client.post(f"/api/v1/healthcare/encounters/{enc.id}/prior-auth",
                                json={"procedure": "MRI lumbar spine", "payer": "Cigna"})
    assert r.status_code == 200, r.text
    body = r.json()
    task = (await db.execute(select(ClinicalTask).where(
        ClinicalTask.id == body["task_id"]))).scalar_one()
    assert task.detail["procedure"] == "MRI lumbar spine"
    assert task.detail["payer"] == "Cigna"


@pytest.mark.asyncio
async def test_prior_auth_route_requires_procedure(async_client: AsyncClient, db):
    enc = await _seed_encounter(db, encounter_number="ENC-R-4")
    r = await async_client.post(f"/api/v1/healthcare/encounters/{enc.id}/prior-auth", json={})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_disclosure_route_goes_through_phi_guard_agent_and_records(async_client: AsyncClient, db):
    r = await async_client.post("/api/v1/healthcare/disclosures", json={
        "purpose": "payment", "recipient": "Acme Payer",
        "fields": ["name", "dob", "member_id", "procedure_codes"],
        "minimum_necessary_justification": "submitting the claim to the payer",
    })
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["authorized"] is True
    disc = (await db.execute(select(PHIDisclosure).where(
        PHIDisclosure.id == body["id"]))).scalar_one()
    assert disc.recorded_by is not None


@pytest.mark.asyncio
async def test_disclosure_route_blocks_excess_fields_and_persists_nothing(async_client: AsyncClient, db):
    r = await async_client.post("/api/v1/healthcare/disclosures", json={
        "purpose": "payment", "recipient": "Acme Payer",
        "fields": ["name", "dob", "member_id", "ssn"],
        "minimum_necessary_justification": "billing the claim",
    })
    assert r.status_code == 422, r.text
    detail = r.json()["detail"]
    assert detail["error"] == "PHI disclosure blocked"

    rows = (await db.execute(select(PHIDisclosure))).scalars().all()
    assert rows == []


@pytest.mark.asyncio
async def test_workflows_endpoint_describes_encounter_and_task_specs(async_client: AsyncClient):
    r = await async_client.get("/api/v1/healthcare/workflows")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["encounter"]["transitions"]["OPEN"] == ["TRIAGED", "CLOSED"]
    assert "DONE" in body["clinical_task"]["states"]
