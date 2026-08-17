"""§06: the /candidates/advance route must not commit a terminal REJECTED stage
without (a) a documented reason and (b) the EEOC four-fifths adverse-impact gate.

These are the compliance guards; each test fails if the guard is removed from
advance_candidate_stage.
"""
import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.hr.models.recruiting import Candidate, CandidateStage


async def _make_req(client: AsyncClient) -> str:
    r = await client.post("/api/v1/hr/requisitions", json={
        "title": "Backend Engineer", "department": "Engineering",
        "hiring_manager_id": "mgr-1", "job_description": "Build APIs.",
    })
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _make_candidate(client: AsyncClient, req_id: str, email: str) -> str:
    r = await client.post("/api/v1/hr/candidates", json={
        "requisition_id": req_id, "first_name": "Test", "last_name": "Cand",
        "email": email,
    })
    assert r.status_code == 201, r.text
    return r.json()["id"]


@pytest.mark.asyncio
async def test_reject_without_reason_is_blocked(async_client: AsyncClient):
    req_id = await _make_req(async_client)
    cand_id = await _make_candidate(async_client, req_id, "no-reason@example.com")

    # No reason -> fail-closed.
    r = await async_client.post(f"/api/v1/hr/candidates/{cand_id}/advance",
                                json={"target_stage": "REJECTED"})
    assert r.status_code == 422, r.text
    # Blank/whitespace reason is still "missing".
    r = await async_client.post(f"/api/v1/hr/candidates/{cand_id}/advance",
                                json={"target_stage": "REJECTED", "reason": "   "})
    assert r.status_code == 422, r.text


@pytest.mark.asyncio
async def test_clean_reject_with_reason_proceeds(async_client: AsyncClient):
    req_id = await _make_req(async_client)
    cand_id = await _make_candidate(async_client, req_id, "clean@example.com")

    # No cohort self-ID data -> EEOC checker is advisory (non-blocking) -> proceeds.
    r = await async_client.post(f"/api/v1/hr/candidates/{cand_id}/advance",
                                json={"target_stage": "REJECTED",
                                      "reason": "Failed technical screen; role requires senior depth."})
    assert r.status_code == 200, r.text
    assert r.json()["stage"] == "REJECTED"


@pytest.mark.asyncio
async def test_reject_blocked_when_cohort_shows_adverse_impact(async_client: AsyncClient, db):
    req_id = await _make_req(async_client)
    # Learn the tenant the API writes under (avoids hardcoding the dev tenant).
    cand_id = await _make_candidate(async_client, req_id, "under-test@example.com")
    tenant_id = (await db.execute(
        select(Candidate.tenant_id).where(Candidate.id == cand_id)
    )).scalar_one()

    # Seed a cohort with statistically-supported adverse impact by gender:
    # males selected at a high rate, females almost never.
    for i in range(30):
        db.add(Candidate(
            tenant_id=tenant_id, requisition_id=req_id,
            first_name="M", last_name=str(i), email=f"m{i}@ex.com",
            stage=CandidateStage.HIRED, eeoc_data={"gender": "male"},
        ))
    for i in range(30):
        db.add(Candidate(
            tenant_id=tenant_id, requisition_id=req_id,
            first_name="F", last_name=str(i), email=f"f{i}@ex.com",
            stage=CandidateStage.REJECTED, eeoc_data={"gender": "female"},
        ))
    await db.commit()

    # Give the candidate under test self-ID so this rejection is part of the cohort.
    cand = (await db.execute(select(Candidate).where(Candidate.id == cand_id))).scalar_one()
    cand.eeoc_data = {"gender": "female"}
    await db.commit()

    r = await async_client.post(f"/api/v1/hr/candidates/{cand_id}/advance",
                                json={"target_stage": "REJECTED", "reason": "Not a fit."})
    assert r.status_code == 422, r.text
    assert "EEOC" in str(r.json()["detail"])

    # Fail-closed means the stage was NOT committed.
    stage = (await db.execute(select(Candidate.stage).where(Candidate.id == cand_id))).scalar_one()
    assert (stage.value if hasattr(stage, "value") else stage) != "REJECTED"


@pytest.mark.asyncio
async def test_non_terminal_advance_needs_no_reason(async_client: AsyncClient):
    req_id = await _make_req(async_client)
    cand_id = await _make_candidate(async_client, req_id, "advance@example.com")
    r = await async_client.post(f"/api/v1/hr/candidates/{cand_id}/advance",
                                json={"target_stage": "RECRUITER_SCREEN"})
    assert r.status_code == 200, r.text
    assert r.json()["stage"] == "RECRUITER_SCREEN"
