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
async def test_world_is_one_connected_graph(async_client: AsyncClient, db):
    await _seed(db)
    r = await async_client.get("/api/v1/neural/world", headers={"X-Tenant-ID": T})
    assert r.status_code == 200
    body = r.json()
    ids = {n["id"] for n in body["nodes"]}
    assert "brain" in ids and "dept-fin" in ids and "dept-hr" in ids
    # every hub feeds the brain, and hubs mesh with each other
    assert any(e["source"] == "dept-fin" and e["target"] == "brain" for e in body["edges"])
    assert any(e["tier"] == "hub-hub" for e in body["edges"])
    # other tenants' clusters are invisible
    assert "dept-x" not in ids


@pytest.mark.asyncio
async def test_world_clusters_match_per_department_build(db):
    """The world fetches every cluster's rows in one query per entity type. That
    is only allowed to be a speed change, so each batched cluster must equal what
    the per-department builder produces on its own."""
    from sqlalchemy import select
    from app.api.routes.neural_helpers import _build_cluster, _build_world_clusters
    from app.workforce.models.core import Department

    await _seed(db)
    depts = (await db.execute(
        select(Department).where(Department.tenant_id == T).order_by(Department.created_at)
    )).scalars().all()
    batched = await _build_world_clusters(db, T, depts)
    assert [d.id for d, _, _ in batched] == [d.id for d in depts]
    for dept, nodes, edges in batched:
        assert (nodes, edges) == await _build_cluster(db, T, dept)


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


async def _seed_new_departments(db):
    """Healthcare/Lending/Procurement + one connected connector each, matching
    the category each department's dept_categories entry expects."""
    from app.models.domain import Connector
    from app.workforce.models.core import Department

    db.add(Department(id="dept-hc", tenant_id=T, name="Healthcare", slug="healthcare", status="ACTIVE"))
    db.add(Department(id="dept-ln", tenant_id=T, name="Lending & Credit", slug="lending", status="ACTIVE"))
    db.add(Department(id="dept-pr", tenant_id=T, name="Procurement", slug="procurement", status="ACTIVE"))
    db.add(Connector(id="conn-ehr", tenant_id=T, name="Clinical EHR",
                      category="clinical", connector_type="API", status="CONNECTED"))
    db.add(Connector(id="conn-los", tenant_id=T, name="Loan Origination System",
                      category="core_banking", connector_type="NATIVE", status="CONNECTED"))
    db.add(Connector(id="conn-esrc", tenant_id=T, name="E-Sourcing Platform",
                      category="procurement", connector_type="API", status="CONNECTED"))
    await db.commit()


@pytest.mark.asyncio
@pytest.mark.parametrize("slug,expected_connector", [
    ("healthcare", "Clinical EHR"),
    ("lending", "Loan Origination System"),
    ("procurement", "E-Sourcing Platform"),
])
async def test_new_departments_get_connector_nodes(async_client: AsyncClient, db, slug, expected_connector):
    """dept_categories used to have no entry for these 3 slugs, so their
    cluster always had zero Connector nodes regardless of what was seeded."""
    await _seed(db)
    await _seed_new_departments(db)
    r = await async_client.get(f"/api/v1/neural/departments/{slug}/graph", headers={"X-Tenant-ID": T})
    assert r.status_code == 200
    body = r.json()
    connectors = [n for n in body["nodes"] if n["type"] == "connector"]
    assert any(n["label"] == expected_connector for n in connectors), (
        f"{slug} cluster has no connector node; got {[n['label'] for n in connectors]}"
    )


@pytest.mark.asyncio
async def test_world_includes_new_department_connectors(async_client: AsyncClient, db):
    """The same fix must hold in the org-wide /neural/world graph, not just
    the single-department view (both share _cluster_graph)."""
    await _seed(db)
    await _seed_new_departments(db)
    r = await async_client.get("/api/v1/neural/world", headers={"X-Tenant-ID": T})
    assert r.status_code == 200
    labels = {n["label"] for n in r.json()["nodes"] if n.get("type") == "connector"}
    assert {"Clinical EHR", "Loan Origination System", "E-Sourcing Platform"} <= labels


def test_seed_connector_catalog_covers_new_departments():
    """The demo connector catalog (backend/app/core/seed.py) must ship at
    least one non-AVAILABLE connector per new department's dept_categories
    category, or the dict entry alone renders nothing on a freshly seeded
    tenant (the cluster filter is `category in dept_categories and status !=
    AVAILABLE`, unless an IntegrationMapping row links it - none are seeded)."""
    from app.core.seed import seed_connectors

    by_category: dict[str, list] = {}
    for c in seed_connectors():
        by_category.setdefault(c.category, []).append(c)

    for category in ("clinical", "core_banking", "procurement"):
        rows = by_category.get(category, [])
        assert rows, f"no seeded connector has category={category!r}"
        assert any(c.status != "AVAILABLE" for c in rows), (
            f"every seeded {category!r} connector is AVAILABLE, so it would "
            "never surface on the Neural Map without a manual integration link"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
