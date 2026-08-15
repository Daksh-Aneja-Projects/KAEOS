"""Cross-cutting ten-department coverage.

The three newest departments (healthcare, lending, procurement) must be
first-class everywhere a department list, alias map, or signal vocabulary is
hardcoded across services that predate them - not silently dropped, and not
folded into "operations" the way procurement used to be aliased.
"""
import uuid
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import select

from app.models.domain import Skill
from app.models.event_mesh import ExternalSignal
from app.core.domain_seed import DEPARTMENT_SLUGS, _DEPT_SLUG_MAP
from app.services import event_mesh
from app.services.missions import planner


# ── app/core/domain_seed.py ──────────────────────────────────────────────────

def test_department_slugs_include_all_ten():
    assert set(DEPARTMENT_SLUGS) == {
        "hr", "finance", "legal", "sales", "support", "operations",
        "engineering", "healthcare", "procurement", "lending",
    }


def test_dept_slug_map_covers_regulated_departments():
    for slug in ("healthcare", "lending", "procurement"):
        assert _DEPT_SLUG_MAP.get(slug) == slug


# ── app/api/routes/platform_config.py ────────────────────────────────────────

def test_autonomy_domains_share_the_department_slugs_source_of_truth():
    from app.api.routes.platform_config import _AUTONOMY_DOMAINS
    assert _AUTONOMY_DOMAINS == DEPARTMENT_SLUGS
    assert {"healthcare", "lending", "procurement"} <= set(_AUTONOMY_DOMAINS)


# ── app/services/missions/planner.py ─────────────────────────────────────────

async def _seed_skill(db, tenant, dept):
    db.add(Skill(id=str(uuid.uuid4()), skill_id=f"{dept}_skill_{uuid.uuid4().hex[:5]}",
                 tenant_id=tenant, department=dept, domain=dept, status="ACTIVE", confidence=0.9))
    await db.commit()


async def test_mission_planner_routes_lending_goal_and_flags_hitl(db):
    t = "tenant_10dept_lending"
    await _seed_skill(db, t, "lending")
    m = await planner.plan_mission(
        db, tenant_id=t,
        goal="Underwrite this loan application and check fair lending exposure")
    assert "lending" in m.departments
    from app.models.missions import MissionStep
    steps = (await db.execute(select(MissionStep).where(MissionStep.mission_id == m.id))).scalars().all()
    lending_step = next(s for s in steps if s.department == "lending")
    assert lending_step.hitl_required is True  # regulated -> high-consequence


async def test_mission_planner_routes_healthcare_goal(db):
    t = "tenant_10dept_health"
    await _seed_skill(db, t, "healthcare")
    m = await planner.plan_mission(
        db, tenant_id=t, goal="Review patient consent before this clinical encounter")
    assert m.departments == ["healthcare"]


async def test_mission_planner_procurement_stays_first_class(db):
    """procurement used to be aliased into "operations" and lose its identity;
    it must now keep its own department + still coexist with real operations
    steps when a goal touches both."""
    t = "tenant_10dept_procurement"
    await _seed_skill(db, t, "procurement")
    await _seed_skill(db, t, "operations")
    m = await planner.plan_mission(
        db, tenant_id=t,
        goal="Run the purchase order three-way match, then check operations capacity")
    assert "procurement" in m.departments
    assert "operations" in m.departments
    assert planner._canon_dept("procurement") == "procurement"


# ── app/services/event_mesh.py ───────────────────────────────────────────────

def test_event_mesh_procurement_is_canonical_not_aliased_to_operations():
    assert "procurement" in event_mesh._CANON
    assert event_mesh._canon_dept("procurement") == "procurement"
    assert event_mesh._ALIAS.get("procurement") is None


async def test_event_mesh_correlates_healthcare_signal_via_synonyms(db):
    t = "tenant_10dept_em_health"
    s = ExternalSignal(tenant_id=t, kind="NEWS",
                       title="New HIPAA guidance affects patient consent workflows",
                       severity="warning")
    db.add(s)
    await event_mesh.correlate(db, t, s)
    assert any(m["name"] == "healthcare" for m in s.matched_entities)


async def test_event_mesh_correlates_lending_signal_via_synonyms(db):
    t = "tenant_10dept_em_lending"
    s = ExternalSignal(tenant_id=t, kind="NEWS",
                       title="Regulator flags fair lending adverse action notice delays",
                       severity="warning")
    db.add(s)
    await event_mesh.correlate(db, t, s)
    assert any(m["name"] == "lending" for m in s.matched_entities)


# ── app/services/workflow_registry.py ────────────────────────────────────────

def test_workflow_registry_includes_all_ten_departments():
    from app.services.workflow_registry import SPECS_BY_ENTITY
    assert "encounter" in SPECS_BY_ENTITY                      # healthcare
    assert "loan_application" in SPECS_BY_ENTITY                # lending
    assert "procurement_purchase_order" in SPECS_BY_ENTITY      # procurement


# ── backend/scripts/seed_master.py ───────────────────────────────────────────

def test_seed_master_wires_the_workforce_graph_phase():
    """Phase 3 used to sync domain packs but never build the org-graph
    (Capability/DepartmentAgent rows) - a script-only seed with no ASGI
    lifespan left a fresh install with zero capabilities/agents."""
    import inspect
    import scripts.seed_master as seed_master
    from app.core.workforce_seed import seed_workforce_graph  # import path must resolve

    src = inspect.getsource(seed_master.run_all_seeds)
    assert "seed_workforce_graph" in src
    assert callable(seed_workforce_graph)


# ── backend/scripts/seed_agent_factory.py ────────────────────────────────────

def test_agent_factory_blueprints_cover_the_newer_departments():
    from scripts.seed_agent_factory import BLUEPRINT_DEFS
    depts = {d["department"] for d in BLUEPRINT_DEFS}
    assert {"engineering", "healthcare", "procurement", "lending"} <= depts


# ── app/core/seed.py ──────────────────────────────────────────────────────────

def test_dept_legal_has_its_actually_enforced_compliance_frameworks():
    """dept_legal used to seed with NO compliance_frameworks while Healthcare/
    Procurement/Lending showed real chips. The tags must match what legal's own
    gates enforce (app/legal/services/compliance_gates.py + the gated
    compliance_tags on contract_review_agent.py), not the longer domain-pack
    aspirational list."""
    from app.core import seed as core_seed
    core_seed.NOW = datetime.now(timezone.utc)
    depts = {d.slug: d for d in core_seed.seed_departments()}
    assert set(depts["legal"].compliance_frameworks) == {
        "CONFLICT_OF_INTEREST", "LEGAL_HOLD", "RETENTION_SCHEDULE",
        "CONTRACT_CLAUSE", "GDPR", "CCPA",
    }


async def test_top_up_backfills_payslips_for_every_payroll_run(db):
    """top_up_new_entities backfilled PayrollRun rows but never created a
    single Payslip, leaving the child table permanently empty."""
    from app.hr.models.core import HREmployee, EmploymentStatus
    from app.hr.models.payroll import PayrollRun, Payslip
    from app.core import seed as core_seed

    core_seed.NOW = datetime.now(timezone.utc)
    t = core_seed.T
    for i in range(3):
        db.add(HREmployee(
            id=f"emp-payslip-{i}", tenant_id=t, first_name="Test", last_name=str(i),
            email=f"payslip{i}@kaeos.ai", status=EmploymentStatus.ACTIVE,
            hire_date=date(2024, 1, 1), job_title="Engineer",
        ))
    await db.commit()

    added = await core_seed.top_up_new_entities(db)
    assert added.get("payroll_runs") == 2
    assert added.get("payslips") == 6  # 2 runs * 3 active employees

    runs = (await db.execute(select(PayrollRun).where(PayrollRun.tenant_id == t))).scalars().all()
    assert len(runs) == 2
    for run in runs:
        slips = (await db.execute(select(Payslip).where(Payslip.run_id == run.id))).scalars().all()
        assert len(slips) == 3
        assert all(s.gross_pay > 0 for s in slips)

    # Idempotent: a second top-up call does not duplicate the child rows.
    added2 = await core_seed.top_up_new_entities(db)
    assert added2.get("payslips", 0) == 0
