"""Neural Map API: department graph shape, dossier derivation, ingest, isolation."""
import pytest
from httpx import AsyncClient

T = "tenant_neural_test"
OTHER = "tenant_neural_other"


async def _seed(db):
    from app.models.domain import Skill
    from app.workforce.models.core import Department, DepartmentAgent

    db.add(Department(
        id="dept-fin", tenant_id=T, name="Finance", slug="finance",
        status="ACTIVE", agent_count=1, health_score=0.9,
    ))
    db.add(Department(
        id="dept-hr", tenant_id=T, name="HR", slug="hr", status="ACTIVE",
    ))
    db.add(DepartmentAgent(
        id="agent-ap", tenant_id=T, department_id="dept-fin",
        agent_name="AP Agent", agent_type="ap_agent",
        role_in_department="Processes vendor invoices", status="ACTIVE",
        skills=["finance_ap_core"], tasks_handled=12,
    ))
    db.add(Skill(
        id="sk-1", skill_id="finance_ap_core", tenant_id=T, department="finance",
        domain="finance", status="ACTIVE", confidence=0.9, always_hitl=False,
        steps=[{"id": "s1", "action": "Match invoice to PO", "tool": "erp"}],
        mcp_tool_bindings=[{"tool": "erp.lookup"}],
    ))
    db.add(Department(id="dept-x", tenant_id=OTHER, name="Secret", slug="secret", status="ACTIVE"))
    await db.commit()


@pytest.mark.asyncio
async def test_department_graph_tiers_and_nav(async_client: AsyncClient, db):
    await _seed(db)
    r = await async_client.get("/api/v1/neural/departments/finance/graph", headers={"X-Tenant-ID": T})
    assert r.status_code == 200
    body = r.json()
    types = {n["type"] for n in body["nodes"]}
    assert {"brain", "department", "agent", "task"} <= types
    # agent → task edge from the agent's own skill list
    assert any(e["source"] == "agent-ap" and e["target"] == "task-finance_ap_core" for e in body["edges"])
    # hub links to the brain
    assert any(e["target"] == "brain" for e in body["edges"])
    # prev/next navigation across the tenant's departments
    assert body["next"] in ("hr", "finance") and body["prev"] is not None


@pytest.mark.asyncio
async def test_agent_dossier_derives_ladder(async_client: AsyncClient, db):
    await _seed(db)
    r = await async_client.get("/api/v1/neural/agents/agent-ap/dossier", headers={"X-Tenant-ID": T})
    assert r.status_code == 200
    d = r.json()
    # no executions yet → the agent starts at the bottom rung
    assert d["autonomy"]["level"] == "human_led"
    assert [x["level"] for x in d["autonomy"]["ladder"]] == ["human_led", "human_assisted", "fully_autonomous"]
    assert d["replaces"]  # every agent explains what it replaces
    assert d["sop"][0]["action"] == "Match invoice to PO"
    assert "erp.lookup" in d["builds_on"]


@pytest.mark.asyncio
async def test_graph_is_tenant_isolated(async_client: AsyncClient, db):
    await _seed(db)
    r = await async_client.get("/api/v1/neural/departments/secret/graph", headers={"X-Tenant-ID": T})
    assert r.status_code == 404  # other tenant's department is invisible


@pytest.mark.asyncio
async def test_map_and_hierarchy(async_client: AsyncClient, db):
    await _seed(db)
    r = await async_client.get("/api/v1/neural/map", headers={"X-Tenant-ID": T})
    assert r.status_code == 200
    assert {d["slug"] for d in r.json()["departments"]} == {"finance", "hr"}
    assert "clusters" in r.json()["brain"]

    h = await async_client.get("/api/v1/neural/hierarchy", headers={"X-Tenant-ID": T})
    assert h.status_code == 200
    fin = next(d for d in h.json()["departments"] if d["slug"] == "finance")
    assert fin["agents"][0]["name"] == "AP Agent"


@pytest.mark.asyncio
async def test_brain_ingest_note(async_client: AsyncClient, db):
    r = await async_client.post(
        "/api/v1/neural/brain/ingest",
        data={"text": "Hotel spend caps at $250 per night.", "domain": "finance"},
        headers={"X-Tenant-ID": T},
    )
    assert r.status_code == 200
    assert r.json()["signal_id"]

    empty = await async_client.post(
        "/api/v1/neural/brain/ingest", data={}, headers={"X-Tenant-ID": T},
    )
    assert empty.status_code == 422


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
