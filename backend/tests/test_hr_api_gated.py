import pytest
from httpx import AsyncClient

# Force the fast simulated LLM path so screening doesn't hit real providers.
from app.services.llm_router import LLMRouter
LLMRouter.provider_available = lambda self, *a, **k: False


@pytest.mark.asyncio
async def test_hr_recruiting_flow(async_client: AsyncClient):
    # The gated pipeline uses the app's AsyncSessionLocal engine (separate from the
    # test get_db override); ensure its schema exists in the shared :memory: DB.
    from app.core.database import init_db
    await init_db()

    # 1. Create a requisition (tenant derived from dev context).
    r = await async_client.post("/api/v1/hr/requisitions", json={
        "title": "Backend Engineer",
        "department": "Engineering",
        "hiring_manager_id": "mgr-1",
        "job_description": "Build APIs.",
        "requirements": ["Python", "FastAPI"],
    })
    assert r.status_code == 201, r.text
    req_id = r.json()["id"]

    # 2. Add a candidate.
    r = await async_client.post("/api/v1/hr/candidates", json={
        "requisition_id": req_id,
        "first_name": "Ada",
        "last_name": "Lovelace",
        "email": "ada@example.com",
    })
    assert r.status_code == 201, r.text
    cand_id = r.json()["id"]
    assert r.json()["stage"] == "APPLIED"

    # 3. Trigger gated AI screening — must return a provenance/execution reference.
    r = await async_client.post(f"/api/v1/hr/candidates/{cand_id}/screen")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "provenance" in body
    assert body["provenance"].get("execution_id")

    # 4. List candidates scoped to the requisition.
    r = await async_client.get(f"/api/v1/hr/candidates?requisition_id={req_id}")
    assert r.status_code == 200
    assert any(c["id"] == cand_id for c in r.json())

    # 5. Advance stage forward is validated (APPLIED -> RECRUITER_SCREEN ok).
    r = await async_client.post(f"/api/v1/hr/candidates/{cand_id}/advance",
                                json={"target_stage": "HM_INTERVIEW"})
    assert r.status_code in (200, 409), r.text

    # 6. Invalid stage is rejected.
    r = await async_client.post(f"/api/v1/hr/candidates/{cand_id}/advance",
                                json={"target_stage": "NOT_A_STAGE"})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_hr_dashboard_uses_tenant_context(async_client: AsyncClient):
    r = await async_client.get("/api/v1/hr/dashboard")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "total_employees" in body and "open_positions" in body
