"""
KAEOS E2E Test 07 — Operations Department
Tests Operations-specific endpoints: projects, resources, vendors,
procurements, inspections, dashboard, and AI agents.
"""
import pytest
from .conftest import assert_dashboard, skip_if_llm_outage


@pytest.mark.asyncio
class TestOperationsDepartment:
    """Operations Department — projects, procurement, vendors, QA."""

    async def test_operations_dashboard(self, client):
        """Operations dashboard returns aggregate metrics."""
        await assert_dashboard(client, "/operations/dashboard")

    async def test_operations_projects(self, client):
        """Projects list returns seeded projects."""
        r = await client.get("/operations/projects")
        assert r.status_code == 200
        projects = r.json()
        assert isinstance(projects, list)
        assert len(projects) > 0, "Expected seeded projects"

    async def test_operations_project_agent(self, client, has_ollama):
        """Project evaluation AI agent."""
        projects = (await client.get("/operations/projects")).json()
        if not projects:
            pytest.skip("No projects")
        # Find a task within a project
        project = projects[0]
        task_id = project.get("id", projects[0]["id"])
        r = await client.post(f"/operations/projects/tasks/{task_id}/evaluate")
        skip_if_llm_outage(r)
        assert r.status_code == 200

    async def test_operations_resources(self, client):
        """Resources list."""
        r = await client.get("/operations/resources")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    async def test_operations_vendors(self, client):
        """Vendors list returns seeded vendors."""
        r = await client.get("/operations/vendors")
        assert r.status_code == 200
        vendors = r.json()
        assert isinstance(vendors, list)
        assert len(vendors) > 0, "Expected seeded operations vendors"

    async def test_operations_vendor_agent(self, client, has_ollama):
        """Vendor evaluation AI agent."""
        vendors = (await client.get("/operations/vendors")).json()
        if not vendors:
            pytest.skip("No vendors")
        r = await client.post(f"/operations/vendors/{vendors[0]['id']}/evaluate")
        skip_if_llm_outage(r)
        assert r.status_code == 200

    async def test_operations_procurements(self, client):
        """Procurements list."""
        r = await client.get("/operations/procurements")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    async def test_operations_procurement_agent(self, client, has_ollama):
        """Procurement audit AI agent."""
        procs = (await client.get("/operations/procurements")).json()
        if not procs:
            pytest.skip("No procurements")
        r = await client.post(f"/operations/procurements/{procs[0]['id']}/audit")
        skip_if_llm_outage(r)
        assert r.status_code == 200

    async def test_operations_inspections(self, client):
        """Quality inspections list."""
        r = await client.get("/operations/inspections")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    async def test_operations_quality_agent(self, client, has_ollama):
        """Quality audit AI agent."""
        inspections = (await client.get("/operations/inspections")).json()
        if not inspections:
            pytest.skip("No inspections")
        r = await client.post(f"/operations/inspections/{inspections[0]['id']}/audit")
        assert r.status_code == 200
