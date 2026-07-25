"""
Phase 1B regression tests — graph subsystem consolidation.

Proves:
  * the fake in-memory "Neo4j" provider (services/graph/neo4j_client.py) and its
    abstract interface (provider.py) are gone;
  * GraphService now delegates to the real polystore GraphStore;
  * FitnessCalculator and ScorecardEngine compute from the REAL graph (no
    hardcoded fixtures) and detect injected structural rot.
"""
import importlib
import os

import pytest

from app.services.graph.graph_service import GraphService
from app.services.evolution.fitness_calculator import FitnessCalculator
from app.services.scorecard_engine import ScorecardEngine

pytestmark = pytest.mark.asyncio

TENANT = "tenant_gc"


async def _clear_graph():
    from sqlalchemy import text
    from app.core.database import MaintenanceSessionLocal
    async with MaintenanceSessionLocal() as s:
        for t in ("polystore_graph_nodes", "polystore_graph_edges"):
            try:
                await s.execute(text(f"DELETE FROM {t}"))
            except Exception:
                pass
        await s.commit()


def test_fake_graph_modules_are_deleted():
    base = os.path.dirname(
        importlib.import_module("app.services.graph.graph_service").__file__
    )
    assert not os.path.exists(os.path.join(base, "neo4j_client.py"))
    assert not os.path.exists(os.path.join(base, "provider.py"))
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("app.services.graph.neo4j_client")


async def test_graph_service_delegates_to_real_store():
    from app.core.polystore.graph_store import Neo4jGraphStore, SqliteGraphStore
    g = GraphService()
    assert isinstance(g.store, (SqliteGraphStore, Neo4jGraphStore))

    await _clear_graph()
    await g.register_entity(TENANT, "gc_n1", "Widget", {"name": "A"})
    await g.register_entity(TENANT, "gc_n2", "Widget", {"name": "B"})
    await g.link_entities(TENANT, "gc_n1", "gc_n2", "FEEDS")

    impact = await g.get_impact_radius(TENANT, "gc_n1", 2)
    assert any(p["downstream"]["id"] == "gc_n2" for p in impact)
    deps = await g.get_dependencies(TENANT, "gc_n2", 2)
    assert any(p["upstream"]["id"] == "gc_n1" for p in deps)


async def test_graph_is_tenant_isolated():
    """One tenant must never see, traverse, or snapshot another tenant's graph."""
    g = GraphService()
    await _clear_graph()

    # Tenant A: a1 -> a2
    await g.register_entity("tenant_a", "a1", "Widget", {"name": "A1"})
    await g.register_entity("tenant_a", "a2", "Widget", {"name": "A2"})
    await g.link_entities("tenant_a", "a1", "a2", "FEEDS")
    # Tenant B: b1 -> b2, and a node reusing tenant A's id "a1"
    await g.register_entity("tenant_b", "b1", "Widget", {"name": "B1"})
    await g.register_entity("tenant_b", "a1", "Widget", {"name": "B-collision"})
    await g.link_entities("tenant_b", "b1", "a1", "FEEDS")

    # Snapshots are disjoint.
    a_nodes, a_edges = await g.snapshot("tenant_a")
    b_nodes, b_edges = await g.snapshot("tenant_b")
    assert set(a_nodes) == {"a1", "a2"}
    assert set(b_nodes) == {"b1", "a1"}
    # The shared id resolves to each tenant's OWN node, not the other's.
    assert a_nodes["a1"]["name"] == "A1"
    assert b_nodes["a1"]["name"] == "B-collision"

    # Traversal cannot cross the tenant boundary.
    a_impact = await g.get_impact_radius("tenant_a", "a1", 3)
    assert {p["downstream"]["id"] for p in a_impact} == {"a2"}
    # Tenant B has no edge out of "a2" (it doesn't own it) and cannot reach tenant A.
    assert await g.get_impact_radius("tenant_b", "a2", 3) == []


async def test_fitness_is_computed_from_real_graph_and_detects_rot():
    g = GraphService()
    await _clear_graph()
    T = "tenant_x"

    await g.register_entity(T, "goal_0", "Goal", {"title": "G"})
    await g.register_entity(T, "cap_0", "Capability", {"name": "AI"})
    await g.register_entity(T, "cap_missing", "Capability", {"name": "Quantum"})

    # Duplicate initiatives: same goal + same required capability
    for i in ("init_a", "init_b"):
        await g.register_entity(T, i, "Initiative", {"title": i})
        await g.link_entities(T, i, "goal_0", "SUPPORTS")
        await g.link_entities(T, i, "cap_0", "REQUIRES_CAPABILITY")

    # Capability gap: requires a capability no employee possesses
    await g.register_entity(T, "init_q", "Initiative", {"title": "Quantum RD"})
    await g.link_entities(T, "init_q", "goal_0", "SUPPORTS")
    await g.link_entities(T, "init_q", "cap_missing", "REQUIRES_CAPABILITY")

    # Projects
    for p in ("proj_0", "proj_1", "proj_2", "proj_3"):
        await g.register_entity(T, p, "Project", {"title": p})
        await g.link_entities(T, p, "init_a", "DELIVERS")

    # Vendor monopoly: v_mono supplies 3 of 4 projects
    await g.register_entity(T, "v_mono", "Vendor", {"name": "Monopoly Corp"})
    await g.register_entity(T, "v_2", "Vendor", {"name": "Other"})
    for p in ("proj_0", "proj_1", "proj_2"):
        await g.link_entities(T, "v_mono", p, "SUPPLIES")
    await g.link_entities(T, "v_2", "proj_3", "SUPPLIES")

    # One employee possesses cap_0 (so init_a/init_b are not blocked); none has cap_missing
    await g.register_entity(T, "emp_0", "Employee", {"name": "E"})
    await g.link_entities(T, "emp_0", "cap_0", "HAS_CAPABILITY")

    # Overload proj_0 far above the mean; give the others one contributor each
    for i in range(40):
        eid = f"emp_load_{i}"
        await g.register_entity(T, eid, "Employee", {"name": eid})
        await g.link_entities(T, eid, "proj_0", "CONTRIBUTES_TO")
    await g.link_entities(T, "emp_0", "proj_1", "CONTRIBUTES_TO")
    await g.link_entities(T, "emp_0", "proj_2", "CONTRIBUTES_TO")
    await g.link_entities(T, "emp_0", "proj_3", "CONTRIBUTES_TO")

    res = await FitnessCalculator(g).calculate_fitness(T)

    assert "simulated" not in res, "fitness must not carry a fixture flag"
    f = res["factors"]
    assert f["vendor_concentration"]["top_vendor"] == "Monopoly Corp"
    assert f["vendor_concentration"]["concentration_pct"] >= 60
    assert res["subscores"]["vendor_fitness"] < 0.6
    assert f["portfolio_waste"]["duplicate_initiatives"] >= 1
    assert "Quantum" in f["capability_gaps"]
    assert "proj_0" in f["overloaded_teams"]
    assert f["graph_size"]["nodes"] > 0


async def test_scorecard_reflects_graph_risk(db):
    g = GraphService()
    await _clear_graph()
    await g.register_entity("tenant_x", "init_x", "Initiative", {"title": "X"})
    await g.register_entity("tenant_x", "risk_x", "Risk", {"title": "R", "severity": "CRITICAL"})
    await g.link_entities("tenant_x", "risk_x", "init_x", "THREATENS")

    card = await ScorecardEngine(g).calculate_enterprise_scorecard(db, "tenant_x")
    assert card["dimensions"]["Initiative_Health"] < 1.0
    assert card["dimensions"]["Risk_Health"] < 1.0
    assert card["graph_size"]["nodes"] >= 2
