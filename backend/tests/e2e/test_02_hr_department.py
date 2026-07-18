"""
KAEOS E2E Test 02 — HR Department
Tests HR-specific endpoints: employees, requisitions, candidates,
time-off requests, performance reviews, dashboard, and AI agents.
"""
import pytest
from .conftest import assert_dashboard


@pytest.mark.asyncio
class TestHRDepartment:
    """HR Department — recruiting, onboarding, performance, time-off."""

    async def test_hr_dashboard(self, client):
        """HR dashboard returns aggregate metrics."""
        await assert_dashboard(client, "/hr/dashboard")

    async def test_hr_employees_list(self, client):
        """Employees list returns seeded employees."""
        r = await client.get("/hr/employees")
        assert r.status_code == 200
        employees = r.json()
        assert isinstance(employees, list)
        assert len(employees) > 0, "Expected seeded HR employees"
        emp = employees[0]
        assert "id" in emp
        assert "first_name" in emp
        assert "status" in emp

    async def test_hr_employee_detail(self, client):
        """Can fetch individual employee."""
        r = await client.get("/hr/employees")
        employees = r.json()
        if employees:
            emp_id = employees[0]["id"]
            r2 = await client.get(f"/hr/employees/{emp_id}")
            assert r2.status_code == 200
            assert r2.json()["id"] == emp_id

    async def test_hr_requisitions_list(self, client):
        """Requisitions list returns seeded job reqs."""
        r = await client.get("/hr/requisitions")
        assert r.status_code == 200
        reqs = r.json()
        assert isinstance(reqs, list)
        assert len(reqs) > 0, "Expected seeded requisitions"

    async def test_hr_candidates_list(self, client):
        """Candidates list returns seeded candidates."""
        r = await client.get("/hr/candidates")
        assert r.status_code == 200
        candidates = r.json()
        assert isinstance(candidates, list)
        assert len(candidates) > 0, "Expected seeded candidates"

    async def test_hr_time_off_requests(self, client):
        """Time-off requests list returns seeded requests."""
        r = await client.get("/hr/time-off-requests")
        assert r.status_code == 200
        reqs = r.json()
        assert isinstance(reqs, list)
        assert len(reqs) > 0, "Expected seeded time-off requests"

    async def test_hr_performance_reviews(self, client):
        """Performance reviews list returns seeded reviews."""
        r = await client.get("/hr/performance-reviews")
        assert r.status_code == 200
        reviews = r.json()
        assert isinstance(reviews, list)
        assert len(reviews) > 0, "Expected seeded performance reviews"

    async def test_hr_create_requisition(self, client):
        """Can create a new job requisition."""
        r = await client.get("/hr/employees")
        employees = r.json()
        manager_id = employees[0]["id"] if employees else "test-manager"
        
        payload = {
            "title": "E2E Test — Senior ML Engineer",
            "department": "Engineering",
            "hiring_manager_id": manager_id,
            "job_description": "Testing requisition creation via E2E test",
            "headcount": 2,
            "requirements": ["Python", "ML", "PyTorch"],
            "target_salary_min": 150000,
            "target_salary_max": 200000,
        }
        r = await client.post("/hr/requisitions", json=payload)
        assert r.status_code in (200, 201)
        data = r.json()
        assert "id" in data
        assert data["status"] in ("DRAFT", "OPEN", "draft", "open")

    async def test_hr_add_candidate(self, client):
        """Can add a candidate to a requisition."""
        reqs = (await client.get("/hr/requisitions")).json()
        if not reqs:
            pytest.skip("No requisitions to add candidate to")
        req_id = reqs[0]["id"]

        payload = {
            "requisition_id": req_id,
            "first_name": "E2E",
            "last_name": "TestCandidate",
            "email": "e2e.test@example.com",
        }
        r = await client.post("/hr/candidates", json=payload)
        assert r.status_code in (200, 201)
        assert "id" in r.json()

    async def test_hr_screen_candidate(self, client, has_ollama):
        """AI screening agent processes a candidate (uses real Ollama)."""
        candidates = (await client.get("/hr/candidates")).json()
        if not candidates:
            pytest.skip("No candidates to screen")

        cand_id = candidates[0]["id"]
        r = await client.post(f"/hr/candidates/{cand_id}/screen")
        assert r.status_code == 200
        data = r.json()
        # Should return AI screening results
        assert isinstance(data, dict)
