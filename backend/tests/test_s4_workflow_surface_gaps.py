"""S4.4 - the workflow HTTP surface is complete in every department.

Healthcare declared two WorkflowSpecs and shipped no way to drive them over
HTTP: no single-entity /transition route and no /workflow-events, so the state
machines only ever moved from inside the gated agents. Lending and procurement
had the transitions but no bulk-transition. These tests pin the now-uniform
surface so a future router edit cannot quietly drop it again.
"""
import pytest
from httpx import AsyncClient

TENANT = "tenant_acme"  # dev-context tenant resolved for unauthenticated tests


async def _seed_encounter(db, tenant_id=TENANT, status="OPEN", suffix="a"):
    from app.healthcare.models.core import PatientEncounter
    e = PatientEncounter(
        tenant_id=tenant_id, encounter_number=f"ENC-S44-{suffix}",
        patient_ref="pt-anon-1", encounter_type="office_visit",
        reason="cough", status=status,
    )
    db.add(e)
    await db.commit()
    await db.refresh(e)
    return e


async def _seed_clinical_task(db, tenant_id=TENANT, status="OPEN"):
    from app.healthcare.models.core import ClinicalTask
    t = ClinicalTask(tenant_id=tenant_id, task_type="coding", status=status)
    db.add(t)
    await db.commit()
    await db.refresh(t)
    return t


# ─── healthcare: single-entity transitions ────────────────────────────────

@pytest.mark.asyncio
async def test_encounter_transition_is_reachable_over_http(async_client: AsyncClient, db):
    e = await _seed_encounter(db, suffix="ok")
    r = await async_client.post(f"/api/v1/healthcare/encounters/{e.id}/transition",
                                json={"to_state": "TRIAGED", "note": "seen by nurse"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["from_state"] == "OPEN"
    assert body["to_state"] == "TRIAGED"
    assert "CODED" in body["allowed_next"]


@pytest.mark.asyncio
async def test_encounter_illegal_move_is_409(async_client: AsyncClient, db):
    e = await _seed_encounter(db, suffix="bad")
    r = await async_client.post(f"/api/v1/healthcare/encounters/{e.id}/transition",
                                json={"to_state": "CODED"})  # OPEN cannot skip triage
    assert r.status_code == 409, r.text
    detail = r.json()["detail"]
    assert detail["error"] == "invalid_transition"
    assert set(detail["allowed"]) == {"TRIAGED", "CLOSED"}


@pytest.mark.asyncio
async def test_encounter_cross_tenant_row_is_404(async_client: AsyncClient, db):
    e = await _seed_encounter(db, tenant_id="tenant_other", suffix="x")
    r = await async_client.post(f"/api/v1/healthcare/encounters/{e.id}/transition",
                                json={"to_state": "TRIAGED"})
    # 404, not 403: a 403 would confirm the foreign id exists.
    assert r.status_code == 404, r.text


@pytest.mark.asyncio
async def test_clinical_task_transition_is_reachable_over_http(async_client: AsyncClient, db):
    t = await _seed_clinical_task(db)
    r = await async_client.post(f"/api/v1/healthcare/tasks/{t.id}/transition",
                                json={"to_state": "IN_PROGRESS"})
    assert r.status_code == 200, r.text
    assert r.json()["from_state"] == "OPEN"
    assert r.json()["to_state"] == "IN_PROGRESS"


# ─── healthcare: the audit trail it never exposed ─────────────────────────

@pytest.mark.asyncio
async def test_healthcare_workflow_events_are_queryable(async_client: AsyncClient, db):
    e = await _seed_encounter(db, suffix="evt")
    await async_client.post(f"/api/v1/healthcare/encounters/{e.id}/transition",
                            json={"to_state": "TRIAGED"})
    r = await async_client.get("/api/v1/healthcare/workflow-events?entity_type=encounter")
    assert r.status_code == 200, r.text
    events = [ev for ev in r.json() if ev["entity_id"] == e.id]
    assert len(events) == 1
    assert events[0]["domain"] == "healthcare"
    assert events[0]["from_state"] == "OPEN"
    assert events[0]["to_state"] == "TRIAGED"


# ─── bulk-transition, the three departments that lacked it ────────────────

@pytest.mark.asyncio
async def test_healthcare_bulk_transition_reports_per_id_outcomes(async_client: AsyncClient, db):
    e = await _seed_encounter(db, suffix="bulk")
    r = await async_client.post("/api/v1/healthcare/workflows/encounter/bulk-transition",
                                json={"ids": [e.id, "no-such-encounter"], "to_state": "TRIAGED"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["requested"] == 2
    assert body["succeeded"] == 1
    assert body["failed"] == 1
    by_id = {row["id"]: row for row in body["results"]}
    assert by_id[e.id]["ok"] is True
    assert by_id["no-such-encounter"]["ok"] is False
    assert by_id["no-such-encounter"]["status_code"] == 404


@pytest.mark.parametrize("domain,entity_type", [
    ("healthcare", "clinical_task"),
    ("lending", "loan_application"),
    ("procurement", "procurement_requisition"),
])
@pytest.mark.asyncio
async def test_bulk_transition_route_exists_and_reports_misses(
    async_client: AsyncClient, db, domain, entity_type
):
    """A bogus id comes back as a per-id failure, not a 404 on the route.

    That distinction is the point: 200 with failed=1 proves the endpoint is
    mounted and the entity type is known, which is what these three
    departments were missing.
    """
    r = await async_client.post(f"/api/v1/{domain}/workflows/{entity_type}/bulk-transition",
                                json={"ids": ["nope"], "to_state": "CANCELLED"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["entity_type"] == entity_type
    assert body["succeeded"] == 0 and body["failed"] == 1
    assert body["results"][0]["ok"] is False


@pytest.mark.parametrize("domain", ["healthcare", "lending", "procurement"])
@pytest.mark.asyncio
async def test_bulk_transition_unknown_entity_type_is_404(async_client: AsyncClient, db, domain):
    r = await async_client.post(f"/api/v1/{domain}/workflows/unicorn/bulk-transition",
                                json={"ids": ["x"], "to_state": "DONE"})
    assert r.status_code == 404, r.text
    assert "unicorn" in r.json()["detail"]
