"""Operations agents: gated-decision persistence, derived (not fabricated)
vendor risk / inspection score, the newly-wired FacilityAgent + WorkOrder,
the removed dead Jira connector, and the seed idempotency guard.

Follows the same monkeypatch-the-gated-runner pattern as
tests/test_sales_gated_agents.py: stub run_gated_operations_skill so these
run without a real LLM, and assert the REAL entity gets written and
committed — the exact CRIT bug this fixes (zero db.add/db.commit across all
5 operations agents).
"""
import json
import uuid

import pytest
from sqlalchemy import select

from app.operations.agents.facility_agent import FacilityAgent
from app.operations.agents.procurement_agent import ProcurementAgent
from app.operations.agents.project_agent import ProjectAgent
from app.operations.agents.qa_agent import QAAgent
from app.operations.agents.resource_agent import ResourceAgent
from app.operations.agents.vendor_agent import VendorAgent
from app.operations.models.facilities import WorkOrder
from app.operations.models.procurement import PurchaseRequest, ProcurementStatus
from app.operations.models.projects import Project, ProjectStatus
from app.operations.models.quality import Inspection, NonConformance, QualityStandard, QualityStatus
from app.operations.models.resources import Resource, ResourceAllocation
from app.operations.models.vendors import VendorContract, VendorPerformance


def _t():
    return f"tenant_ops_{uuid.uuid4().hex[:8]}"


def _id():
    return str(uuid.uuid4())


def _stub(monkeypatch, module_path: str, *, status="SUCCESS_CLEAN", decision=None, **extra):
    """Patch run_gated_operations_skill where the agent module imported it,
    exactly like test_sales_gated_agents.py's _stub_gated_sales."""
    calls = {}

    async def fake(skill_id, steps, context, tenant_id, *, compliance_tags=None,
                   confidence=0.85, domain="operations"):
        calls["skill_id"] = skill_id
        calls["compliance_tags"] = compliance_tags
        calls["context"] = context
        if status == "SUCCESS_CLEAN":
            payload = decision if decision is not None else {}
            return {"status": "SUCCESS_CLEAN", "execution_id": "exec-ops",
                    "reasoning_chain": [{"decision": json.dumps(payload)}]}
        return {"status": status, "execution_id": "exec-ops", **extra}

    monkeypatch.setattr(f"{module_path}.run_gated_operations_skill", fake)
    return calls


# ── ProjectAgent ─────────────────────────────────────────────────────────

async def test_project_agent_persists_ai_risk_note_on_success(db, monkeypatch):
    tenant = _t()
    project = Project(id=_id(), tenant_id=tenant, name="Node Expansion",
                      status=ProjectStatus.ACTIVE, completion_percentage=40.0)
    db.add(project)
    await db.commit()

    _stub(monkeypatch, "app.operations.agents.project_agent", decision={
        "on_track": False, "delay_risk": "HIGH",
        "blockers": ["vendor SLA breach"], "recommended_action": "Escalate to PM",
    })
    result = await ProjectAgent().evaluate_project(db, project.id, tenant)
    assert result["status"] == "SUCCESS_CLEAN"

    refreshed = (await db.execute(select(Project).where(Project.id == project.id))).scalar_one()
    assert refreshed.ai_risk_note is not None
    assert "High" in refreshed.ai_risk_note or "HIGH" in refreshed.ai_risk_note
    assert "vendor SLA breach" in refreshed.ai_risk_note
    assert "Escalate to PM" in refreshed.ai_risk_note


async def test_project_agent_clears_note_when_healthy(db, monkeypatch):
    tenant = _t()
    project = Project(id=_id(), tenant_id=tenant, name="Healthy Project",
                      status=ProjectStatus.ACTIVE, completion_percentage=90.0,
                      ai_risk_note="STALE: previously flagged HIGH risk.")
    db.add(project)
    await db.commit()

    _stub(monkeypatch, "app.operations.agents.project_agent", decision={"on_track": True})
    await ProjectAgent().evaluate_project(db, project.id, tenant)

    refreshed = (await db.execute(select(Project).where(Project.id == project.id))).scalar_one()
    assert refreshed.ai_risk_note is None


async def test_project_agent_missing_project_raises(db, monkeypatch):
    with pytest.raises(ValueError):
        await ProjectAgent().evaluate_project(db, "nope", _t())


async def test_project_agent_pending_hitl_does_not_touch_entity(db, monkeypatch):
    tenant = _t()
    project = Project(id=_id(), tenant_id=tenant, name="Paused Project",
                      status=ProjectStatus.ACTIVE, ai_risk_note=None)
    db.add(project)
    await db.commit()

    _stub(monkeypatch, "app.operations.agents.project_agent", status="PENDING_HITL")
    result = await ProjectAgent().evaluate_project(db, project.id, tenant)
    assert result["status"] == "PENDING_HITL"
    refreshed = (await db.execute(select(Project).where(Project.id == project.id))).scalar_one()
    assert refreshed.ai_risk_note is None


# ── ResourceAgent ────────────────────────────────────────────────────────

async def test_resource_agent_check_overload_persists_rebalance_note(db, monkeypatch):
    tenant = _t()
    resource = Resource(id=_id(), tenant_id=tenant, name="Senior QA Engineer",
                        resource_type="DEVELOPER", cost_per_hour=75.0)
    db.add(resource)
    await db.flush()
    alloc = ResourceAllocation(id=_id(), tenant_id=tenant, resource_id=resource.id,
                               project_id=_id(), allocated_hours=45.0, utilization_percentage=112.5)
    db.add(alloc)
    await db.commit()

    _stub(monkeypatch, "app.operations.agents.resource_agent", decision={
        "overload_confirmed": True, "recommended_action": "Shift 10h to a second engineer",
        "rebalance_plan": "Move backend testing to QA2",
    })
    result = await ResourceAgent().check_overload(db, alloc.id, tenant)
    assert result["overloaded"] is True

    refreshed = (await db.execute(
        select(ResourceAllocation).where(ResourceAllocation.id == alloc.id)
    )).scalar_one()
    assert refreshed.ai_rebalance_note is not None
    assert "Move backend testing to QA2" in refreshed.ai_rebalance_note


async def test_resource_agent_missing_allocation_raises(db):
    with pytest.raises(ValueError):
        await ResourceAgent().check_overload(db, "nope", _t())


# ── VendorAgent ──────────────────────────────────────────────────────────

async def test_vendor_agent_persists_ai_recommendation(db, monkeypatch):
    tenant = _t()
    contract = VendorContract(id=_id(), tenant_id=tenant, vendor_name="Dublin Cloud Hosting",
                              service_provided="Infra", contract_value=45000.0)
    db.add(contract)
    await db.commit()

    _stub(monkeypatch, "app.operations.agents.vendor_agent", decision={
        "risk_level": "low", "renew_recommendation": "Renew for 2 years",
        "concerns": ["none material"],
    })
    result = await VendorAgent().evaluate_vendor(db, contract.id, tenant)
    assert result["status"] == "SUCCESS_CLEAN"

    refreshed = (await db.execute(
        select(VendorContract).where(VendorContract.id == contract.id)
    )).scalar_one()
    assert refreshed.ai_recommendation is not None
    assert "Renew for 2 years" in refreshed.ai_recommendation
    assert "Low" in refreshed.ai_recommendation


async def test_vendor_agent_missing_contract_raises(db):
    with pytest.raises(ValueError):
        await VendorAgent().evaluate_vendor(db, "nope", _t())


# ── ProcurementAgent ─────────────────────────────────────────────────────

async def test_procurement_agent_persists_audit_note(db, monkeypatch):
    tenant = _t()
    req = PurchaseRequest(id=_id(), tenant_id=tenant, item_description="10x Laptops",
                          quantity=10, unit_price=1999.0, total_estimated_cost=19990.0,
                          status=ProcurementStatus.PENDING_APPROVAL)
    db.add(req)
    await db.commit()

    _stub(monkeypatch, "app.operations.agents.procurement_agent", decision={
        "compliant": True, "price_reasonable": False,
        "flags": ["above market rate"], "approve_or_review": "REVIEW",
    })
    result = await ProcurementAgent().audit_request(db, req.id, tenant)
    assert result["status"] == "SUCCESS_CLEAN"

    refreshed = (await db.execute(
        select(PurchaseRequest).where(PurchaseRequest.id == req.id)
    )).scalar_one()
    assert refreshed.ai_audit_note is not None
    assert "above market rate" in refreshed.ai_audit_note
    # The workflow status itself is untouched by the agent — it still moves
    # only through the governed /transition endpoint.
    assert refreshed.status == ProcurementStatus.PENDING_APPROVAL


async def test_procurement_agent_missing_request_raises(db):
    with pytest.raises(ValueError):
        await ProcurementAgent().audit_request(db, "nope", _t())


# ── QAAgent ──────────────────────────────────────────────────────────────

async def test_qa_agent_flips_status_and_persists_summary(db, monkeypatch):
    tenant = _t()
    standard = QualityStandard(id=_id(), tenant_id=tenant, name="ISO-9001")
    db.add(standard)
    await db.flush()
    insp = Inspection(id=_id(), tenant_id=tenant, standard_id=standard.id,
                      inspected_item="Backup script", inspector="Oscar",
                      status=QualityStatus.IN_PROGRESS)
    db.add(insp)
    await db.commit()

    _stub(monkeypatch, "app.operations.agents.qa_agent", decision={
        "pass_or_fail": "FAIL", "defects": ["missing audit log"],
        "corrective_actions": ["add metadata logger"],
    })
    result = await QAAgent().inspect_qa(db, insp.id, tenant)
    assert result["status"] == "SUCCESS_CLEAN"

    refreshed = (await db.execute(select(Inspection).where(Inspection.id == insp.id))).scalar_one()
    assert refreshed.status == QualityStatus.FAILED
    assert "missing audit log" in refreshed.ai_summary
    assert "add metadata logger" in refreshed.ai_summary


async def test_qa_agent_unrecognized_verdict_leaves_status_unchanged(db, monkeypatch):
    tenant = _t()
    standard = QualityStandard(id=_id(), tenant_id=tenant, name="ISO-9001")
    db.add(standard)
    await db.flush()
    insp = Inspection(id=_id(), tenant_id=tenant, standard_id=standard.id,
                      inspected_item="Backup script", inspector="Oscar",
                      status=QualityStatus.IN_PROGRESS)
    db.add(insp)
    await db.commit()

    _stub(monkeypatch, "app.operations.agents.qa_agent", decision={"pass_or_fail": "INCONCLUSIVE"})
    await QAAgent().inspect_qa(db, insp.id, tenant)

    refreshed = (await db.execute(select(Inspection).where(Inspection.id == insp.id))).scalar_one()
    assert refreshed.status == QualityStatus.IN_PROGRESS


async def test_qa_agent_missing_inspection_raises(db):
    with pytest.raises(ValueError):
        await QAAgent().inspect_qa(db, "nope", _t())


# ── FacilityAgent (newly wired) ──────────────────────────────────────────

async def test_facility_agent_deterministic_priority_persists_even_when_blocked(db, monkeypatch):
    """The priority is never an LLM guess: it is written and committed
    regardless of how the compliance gate resolves."""
    tenant = _t()
    wo = WorkOrder(id=_id(), tenant_id=tenant, facility_name="Dublin DC",
                   issue_title="Gas leak near generator", category="SAFETY", status="OPEN")
    db.add(wo)
    await db.commit()

    _stub(monkeypatch, "app.operations.agents.facility_agent", status="BLOCKED_COMPLIANCE",
          violations=[{"framework": "INCIDENT_POSTMORTEM", "reason": "x"}])
    result = await FacilityAgent().triage_work_order(db, wo.id, tenant)
    assert result["status"] == "BLOCKED_COMPLIANCE"

    refreshed = (await db.execute(select(WorkOrder).where(WorkOrder.id == wo.id))).scalar_one()
    assert refreshed.priority == "URGENT"  # safety keyword forces URGENT
    assert refreshed.safety_flagged is True
    assert refreshed.ai_notes is None  # no SUCCESS_CLEAN decision to summarize


async def test_facility_agent_routes_change_context_for_maintenance(db, monkeypatch):
    tenant = _t()
    wo = WorkOrder(id=_id(), tenant_id=tenant, facility_name="AWS Ireland Cluster",
                   issue_title="Rotate TLS certificate", category="MAINTENANCE", status="OPEN",
                   severity="HIGH", is_production=True, implementer="dev@x",
                   approver="lead@x", change_ticket="CHG-1")
    db.add(wo)
    await db.commit()

    calls = _stub(monkeypatch, "app.operations.agents.facility_agent",
                  decision={"risk_assessment": "Low risk", "recommended_next_step": "Proceed"})
    result = await FacilityAgent().triage_work_order(db, wo.id, tenant)

    assert "CHANGE_MANAGEMENT" in calls["compliance_tags"]
    assert calls["context"]["change"] == {
        "is_production": True, "implementer": "dev@x", "approver": "lead@x", "ticket": "CHG-1",
    }
    assert "incident" not in calls["context"]
    assert "retention" not in calls["context"]
    assert result["priority"] == "URGENT"  # HIGH severity


async def test_facility_agent_routes_incident_context_for_safety(db, monkeypatch):
    tenant = _t()
    wo = WorkOrder(id=_id(), tenant_id=tenant, facility_name="Dublin DC - Floor 2",
                   issue_title="Cooling unit short", category="SAFETY", status="RESOLVED",
                   severity="SEV2", root_cause="Corroded terminal block",
                   action_items="Replace terminal block\nAdd quarterly inspection")
    db.add(wo)
    await db.commit()

    calls = _stub(monkeypatch, "app.operations.agents.facility_agent",
                  decision={"risk_assessment": "Contained", "recommended_next_step": "Close out"})
    await FacilityAgent().triage_work_order(db, wo.id, tenant)

    assert calls["context"]["incident"] == {
        "severity": "SEV2", "status": "resolved",
        "postmortem": {
            "root_cause": "Corroded terminal block",
            "action_items": ["Replace terminal block", "Add quarterly inspection"],
        },
    }
    assert "change" not in calls["context"]
    assert "retention" not in calls["context"]


async def test_facility_agent_routes_retention_context_for_decommission(db, monkeypatch):
    tenant = _t()
    wo = WorkOrder(id=_id(), tenant_id=tenant, facility_name="Legacy FS-03",
                   issue_title="Decommission file server", category="DECOMMISSION", status="OPEN",
                   backup_verified=True, record_age_days=920.0, retention_days=365.0)
    db.add(wo)
    await db.commit()

    calls = _stub(monkeypatch, "app.operations.agents.facility_agent",
                  decision={"risk_assessment": "Clear", "recommended_next_step": "Proceed with wipe"})
    await FacilityAgent().triage_work_order(db, wo.id, tenant)

    assert calls["context"]["retention"] == {
        "operation": "delete", "record_age_days": 920.0,
        "retention_days": 365.0, "backup_verified": True,
    }
    assert "change" not in calls["context"]
    assert "incident" not in calls["context"]


async def test_facility_agent_missing_work_order_raises(db):
    with pytest.raises(ValueError):
        await FacilityAgent().triage_work_order(db, "nope", _t())


# ── Compliance checkers actually resolve against FacilityAgent's real
#    context shapes (no LLM, no mock — the deterministic checkers themselves) ──

def test_change_management_checker_resolves_facility_agent_maintenance_shape():
    from app.compliance import run_checks
    ctx = {"change": {"is_production": True, "implementer": "dev@x",
                      "approver": "dev@x", "ticket": None}}
    res = run_checks(["CHANGE_MANAGEMENT"], ctx)
    assert res["verified"] is False  # self-approval + no ticket


def test_incident_postmortem_checker_resolves_facility_agent_safety_shape():
    from app.compliance import run_checks
    ctx = {"incident": {"severity": "SEV2", "status": "resolved",
                        "postmortem": {"root_cause": "Corroded terminal block",
                                       "action_items": ["Replace terminal block"]}}}
    res = run_checks(["INCIDENT_POSTMORTEM"], ctx)
    assert res["verified"] is True


def test_backup_retention_checker_resolves_facility_agent_decommission_shape():
    from app.compliance import run_checks
    ctx = {"retention": {"operation": "delete", "record_age_days": 920.0,
                         "retention_days": 365.0, "backup_verified": True}}
    res = run_checks(["BACKUP_RETENTION"], ctx)
    assert res["verified"] is True


# ── Router: vendor risk_level derived, never fabricated ─────────────────

async def test_vendors_endpoint_derives_risk_level_from_performance(async_client, db):
    tenant = "tenant_acme"
    contract = VendorContract(id=_id(), tenant_id=tenant, vendor_name="Excellent Vendor Co",
                              service_provided="Hosting", contract_value=10000.0)
    db.add(contract)
    await db.flush()
    db.add(VendorPerformance(id=_id(), tenant_id=tenant, vendor_contract_id=contract.id,
                             overall_performance_score=96.5))
    await db.commit()

    r = await async_client.get("/api/v1/operations/vendors")
    assert r.status_code == 200, r.text
    row = next(v for v in r.json() if v["id"] == contract.id)
    assert row["risk_level"] == "LOW"
    assert row["performance_score"] == 96.5
    assert row["soc2_verified"] is None  # honestly untracked, never fabricated


async def test_vendors_endpoint_no_performance_is_not_scored(async_client, db):
    tenant = "tenant_acme"
    contract = VendorContract(id=_id(), tenant_id=tenant, vendor_name="New Vendor No History",
                              service_provided="Consulting", contract_value=5000.0)
    db.add(contract)
    await db.commit()

    r = await async_client.get("/api/v1/operations/vendors")
    assert r.status_code == 200, r.text
    row = next(v for v in r.json() if v["id"] == contract.id)
    assert row["risk_level"] is None  # no fabricated "MEDIUM" default
    assert row["performance_score"] is None


# ── Router: inspection score derived from real defects, not a status lookup ─

async def test_inspections_endpoint_derives_score_from_defects(async_client, db):
    tenant = "tenant_acme"
    standard = QualityStandard(id=_id(), tenant_id=tenant, name="ISO-9001")
    db.add(standard)
    await db.flush()
    insp = Inspection(id=_id(), tenant_id=tenant, standard_id=standard.id,
                      inspected_item="Line 4 audit", inspector="Oscar",
                      status=QualityStatus.IN_PROGRESS)
    db.add(insp)
    await db.flush()
    db.add(NonConformance(id=_id(), tenant_id=tenant, inspection_id=insp.id,
                          defect_description="Missing metadata", impact_rating="HIGH"))
    await db.commit()

    r = await async_client.get("/api/v1/operations/inspections")
    assert r.status_code == 200, r.text
    row = next(i for i in r.json() if i["id"] == insp.id)
    # IN_PROGRESS used to be a flat 50 regardless of defects; now 100 - 20 (HIGH).
    assert row["score"] == 80
    assert row["defects"] == 1


async def test_inspections_endpoint_passed_with_zero_defects_scores_100(async_client, db):
    tenant = "tenant_acme"
    standard = QualityStandard(id=_id(), tenant_id=tenant, name="ISO-9001")
    db.add(standard)
    await db.flush()
    insp = Inspection(id=_id(), tenant_id=tenant, standard_id=standard.id,
                      inspected_item="Clean pass", inspector="Oscar",
                      status=QualityStatus.PASSED)
    db.add(insp)
    await db.commit()

    r = await async_client.get("/api/v1/operations/inspections")
    row = next(i for i in r.json() if i["id"] == insp.id)
    assert row["score"] == 100


# ── Router: work orders (list / create / triage) ─────────────────────────

async def test_work_orders_create_and_list(async_client, db):
    r = await async_client.post("/api/v1/operations/work-orders", json={
        "facility_name": "Test Facility", "issue_title": "Broken elevator",
        "category": "maintenance", "severity": "MEDIUM",
    })
    assert r.status_code == 201, r.text
    created = r.json()
    assert created["category"] == "MAINTENANCE"  # normalized upper

    r = await async_client.get("/api/v1/operations/work-orders")
    assert r.status_code == 200, r.text
    assert any(w["id"] == created["id"] for w in r.json())


async def test_work_orders_triage_endpoint_persists_and_returns(async_client, db, monkeypatch):
    tenant = "tenant_acme"
    wo = WorkOrder(id=_id(), tenant_id=tenant, facility_name="Test Facility 2",
                   issue_title="Replace air filter", category="MAINTENANCE", status="OPEN",
                   severity="LOW")
    db.add(wo)
    await db.commit()

    _stub(monkeypatch, "app.operations.agents.facility_agent",
          decision={"risk_assessment": "Minor", "recommended_next_step": "Schedule routine"})
    r = await async_client.post(f"/api/v1/operations/work-orders/{wo.id}/triage")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["priority"] == "LOW"
    assert body["status"] == "SUCCESS_CLEAN"


async def test_work_orders_triage_unknown_id_returns_404(async_client, db):
    r = await async_client.post("/api/v1/operations/work-orders/does-not-exist/triage")
    assert r.status_code == 404


# ── Seed: idempotency guard + TaskDependency + work orders ───────────────

async def test_seed_is_idempotent_and_covers_task_dependencies_and_work_orders(db):
    from app.operations import seed as ops_seed
    from app.operations.models.projects import TaskDependency

    tenant = _t()
    ran = await ops_seed.seed_tenant(db, tenant=tenant)
    assert ran is True

    deps = (await db.execute(
        select(TaskDependency).where(TaskDependency.tenant_id == tenant)
    )).scalars().all()
    assert len(deps) >= 2

    orders = (await db.execute(
        select(WorkOrder).where(WorkOrder.tenant_id == tenant)
    )).scalars().all()
    categories = {o.category for o in orders}
    assert categories == {"MAINTENANCE", "SAFETY", "DECOMMISSION"}

    # Re-running must not duplicate rows.
    ran_again = await ops_seed.seed_tenant(db, tenant=tenant)
    assert ran_again is False
    orders_again = (await db.execute(
        select(WorkOrder).where(WorkOrder.tenant_id == tenant)
    )).scalars().all()
    assert len(orders_again) == len(orders)


# ── Dead Jira connector duplicate removed ─────────────────────────────────

def test_operations_connectors_package_removed():
    with pytest.raises(ModuleNotFoundError):
        import app.operations.connectors  # noqa: F401
