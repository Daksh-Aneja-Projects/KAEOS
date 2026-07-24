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
    await g.register_entity("gc_n1", "Widget", {"name": "A"})
    await g.register_entity("gc_n2", "Widget", {"name": "B"})
    await g.link_entities("gc_n1", "gc_n2", "FEEDS")

    impact = await g.get_impact_radius("gc_n1", 2)
    assert any(p["downstream"]["id"] == "gc_n2" for p in impact)
    deps = await g.get_dependencies("gc_n2", 2)
    assert any(p["upstream"]["id"] == "gc_n1" for p in deps)


async def test_fitness_is_computed_from_real_graph_and_detects_rot():
    g = GraphService()
    await _clear_graph()

    await g.register_entity("goal_0", "Goal", {"title": "G"})
    await g.register_entity("cap_0", "Capability", {"name": "AI"})
    await g.register_entity("cap_missing", "Capability", {"name": "Quantum"})

    # Duplicate initiatives: same goal + same required capability
    for i in ("init_a", "init_b"):
        await g.register_entity(i, "Initiative", {"title": i})
        await g.link_entities(i, "goal_0", "SUPPORTS")
        await g.link_entities(i, "cap_0", "REQUIRES_CAPABILITY")

    # Capability gap: requires a capability no employee possesses
    await g.register_entity("init_q", "Initiative", {"title": "Quantum RD"})
    await g.link_entities("init_q", "goal_0", "SUPPORTS")
    await g.link_entities("init_q", "cap_missing", "REQUIRES_CAPABILITY")

    # Projects
    for p in ("proj_0", "proj_1", "proj_2", "proj_3"):
        await g.register_entity(p, "Project", {"title": p})
        await g.link_entities(p, "init_a", "DELIVERS")

    # Vendor monopoly: v_mono supplies 3 of 4 projects
    await g.register_entity("v_mono", "Vendor", {"name": "Monopoly Corp"})
    await g.register_entity("v_2", "Vendor", {"name": "Other"})
    for p in ("proj_0", "proj_1", "proj_2"):
        await g.link_entities("v_mono", p, "SUPPLIES")
    await g.link_entities("v_2", "proj_3", "SUPPLIES")

    # One employee possesses cap_0 (so init_a/init_b are not blocked); none has cap_missing
    await g.register_entity("emp_0", "Employee", {"name": "E"})
    await g.link_entities("emp_0", "cap_0", "HAS_CAPABILITY")

    # Overload proj_0 far above the mean; give the others one contributor each
    for i in range(40):
        eid = f"emp_load_{i}"
        await g.register_entity(eid, "Employee", {"name": eid})
        await g.link_entities(eid, "proj_0", "CONTRIBUTES_TO")
    await g.link_entities("emp_0", "proj_1", "CONTRIBUTES_TO")
    await g.link_entities("emp_0", "proj_2", "CONTRIBUTES_TO")
    await g.link_entities("emp_0", "proj_3", "CONTRIBUTES_TO")

    res = await FitnessCalculator(g).calculate_fitness("tenant_x")

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
    await g.register_entity("init_x", "Initiative", {"title": "X"})
    await g.register_entity("risk_x", "Risk", {"title": "R", "severity": "CRITICAL"})
    await g.link_entities("risk_x", "init_x", "THREATENS")

    card = await ScorecardEngine(g).calculate_enterprise_scorecard(db, "tenant_x")
    assert card["dimensions"]["Initiative_Health"] < 1.0
    assert card["dimensions"]["Risk_Health"] < 1.0
    assert card["graph_size"]["nodes"] >= 2
