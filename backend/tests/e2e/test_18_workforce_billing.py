"""
KAEOS E2E Test 18 — Workforce Layer, Domain Packs & Billing
Tests department detail pages, the deployment state machine
(start → advance), domain pack catalog install/uninstall, workforce
processes, billing usage/ROI, and the top-level departments API.
"""
import pytest


@pytest.mark.asyncio
class TestWorkforceDepartments:
    """Workforce department pages — detail, capabilities, agents."""

    async def _first_dept(self, client):
        r = await client.get("/workforce/departments")
        assert r.status_code == 200
        data = r.json()
        depts = data.get("departments", data) if isinstance(data, dict) else data
        assert isinstance(depts, list) and depts, "Expected seeded departments"
        return depts[0]

    async def test_department_detail(self, client):
        dept = await self._first_dept(client)
        dept_id = dept.get("id") or dept.get("slug")
        r = await client.get(f"/workforce/departments/{dept_id}")
        assert r.status_code == 200, f"{r.status_code}: {r.text[:300]}"

    async def test_department_detail_404(self, client):
        r = await client.get("/workforce/departments/not_a_department")
        assert r.status_code == 404

    async def test_all_departments_have_capabilities(self, client):
        """Every seeded department exposes a capabilities endpoint."""
        r = await client.get("/workforce/departments")
        data = r.json()
        depts = data.get("departments", data) if isinstance(data, dict) else data
        assert len(depts) >= 6, f"Expected all 6 departments, got {len(depts)}"
        for dept in depts:
            dept_id = dept.get("id") or dept.get("slug")
            r2 = await client.get(f"/workforce/departments/{dept_id}/capabilities")
            assert r2.status_code == 200, f"capabilities for {dept_id} → {r2.status_code}"


@pytest.mark.asyncio
class TestDomainPacks:
    """Domain pack catalog — list, detail, install, uninstall."""

    async def test_packs_list(self, client):
        r = await client.get("/workforce/packs/")
        assert r.status_code == 200
        data = r.json()
        packs = data.get("packs", data) if isinstance(data, dict) else data
        assert isinstance(packs, list)
        assert len(packs) >= 1, "Expected built-in domain packs"
        TestDomainPacks._pack_id = packs[0].get("id")

    async def test_pack_detail(self, client):
        pack_id = getattr(TestDomainPacks, "_pack_id", None)
        if not pack_id:
            pytest.skip("No packs listed")
        r = await client.get(f"/workforce/packs/{pack_id}")
        assert r.status_code == 200

    async def test_pack_installations(self, client):
        r = await client.get("/workforce/packs/installations")
        assert r.status_code == 200

    async def test_pack_install_uninstall(self, client):
        pack_id = getattr(TestDomainPacks, "_pack_id", None)
        if not pack_id:
            pytest.skip("No packs listed")
        r = await client.post(f"/workforce/packs/{pack_id}/install")
        assert r.status_code == 200
        r2 = await client.post(f"/workforce/packs/{pack_id}/uninstall")
        assert r2.status_code == 200


@pytest.mark.asyncio
class TestDeploymentStateMachine:
    """Deployment studio — start a deployment and advance it."""

    async def test_deployments_list(self, client):
        r = await client.get("/workforce/deployments/")
        assert r.status_code == 200

    async def test_start_and_advance_deployment(self, client):
        packs_data = (await client.get("/workforce/packs/")).json()
        packs = packs_data.get("packs", packs_data) if isinstance(packs_data, dict) else packs_data
        if not packs:
            pytest.skip("No domain packs to deploy")
        pack = packs[0]

        r = await client.post("/workforce/deployments/start", json={
            "domain_pack_id": pack["id"],
            "domain_pack_slug": pack.get("slug"),
            "selected_capabilities": [],
            "connected_systems": [],
            "employee_count": 10,
        })
        assert r.status_code == 200, f"start → {r.status_code}: {r.text[:300]}"
        dep_id = r.json()["id"]

        # Deployment detail
        r2 = await client.get(f"/workforce/deployments/{dep_id}")
        assert r2.status_code == 200
        assert r2.json()["id"] == dep_id

        # Advance one step
        r3 = await client.post(f"/workforce/deployments/{dep_id}/advance",
                               json={"step_data": {}})
        assert r3.status_code == 200, f"advance → {r3.status_code}: {r3.text[:300]}"


@pytest.mark.asyncio
class TestProcessesAndAnalytics:
    """Workforce processes and analytics."""

    async def test_processes_list(self, client):
        r = await client.get("/workforce/processes")
        assert r.status_code == 200

    async def test_process_detail(self, client):
        r = await client.get("/workforce/processes")
        data = r.json()
        procs = data.get("processes", data) if isinstance(data, dict) else data
        if not (isinstance(procs, list) and procs):
            pytest.skip("No workforce processes seeded")
        proc_id = procs[0].get("id")
        r2 = await client.get(f"/workforce/processes/{proc_id}")
        assert r2.status_code == 200

    async def test_enterprise_processes(self, client):
        """Enterprise-level processes endpoint — must surface the seeded workflows."""
        r = await client.get("/processes")
        assert r.status_code == 200
        data = r.json()
        procs = data.get("processes", [])
        assert data.get("total", 0) >= 1 and procs, "Seeded workflows missing from /processes"
        for key in ("id", "name", "department", "status", "sla_hours"):
            assert key in procs[0], f"Missing '{key}' in process. Keys: {list(procs[0].keys())}"

    async def test_enterprise_workforces(self, client):
        r = await client.get("/workforces")
        assert r.status_code == 200
        data = r.json()
        forces = data.get("workforces", [])
        assert data.get("total", 0) >= 1 and forces, "No workforces returned"
        assert "agent_name" in forces[0] and "status" in forces[0]


@pytest.mark.asyncio
class TestDepartmentsAndBilling:
    """Top-level departments API + billing usage/ROI."""

    async def test_departments_list(self, client):
        r = await client.get("/departments")
        assert r.status_code == 200
        data = r.json()
        depts = data.get("departments", data) if isinstance(data, dict) else data
        assert isinstance(depts, list)
        assert len(depts) >= 6, f"Expected 6 departments, got {len(depts)}"

    async def test_department_capabilities(self, client):
        data = (await client.get("/departments")).json()
        depts = data.get("departments", data) if isinstance(data, dict) else data
        dept_id = depts[0].get("id") or depts[0].get("slug")
        r = await client.get(f"/departments/{dept_id}/capabilities")
        assert r.status_code == 200

    async def test_billing_usage(self, client):
        r = await client.get("/billing/usage")
        assert r.status_code == 200
        assert isinstance(r.json(), dict)

    async def test_billing_roi(self, client):
        r = await client.get("/billing/roi")
        assert r.status_code == 200
        assert isinstance(r.json(), dict)
