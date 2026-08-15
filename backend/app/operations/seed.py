"""
KAEOS Operations Domain — Database Seed Script
Seeds the Operations tables with projects, team allocations, purchase requests,
facility work orders, and quality standards.
"""
import asyncio
import uuid
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select

from app.core.database import async_engine, AsyncSessionLocal
from app.models.domain import Base

# Models imports
from app.operations.models.core import OpsTeamMember, DepartmentConfig
from app.operations.models.projects import Project, Milestone, Task, TaskDependency, ProjectStatus
from app.operations.models.resources import Resource, ResourceAllocation, CapacityPlan
from app.operations.models.vendors import VendorContract, VendorPerformance
from app.operations.models.procurement import PurchaseRequest, PurchaseOrder, POLineItem, GoodsReceipt, ProcurementStatus
from app.operations.models.quality import QualityStandard, Inspection, NonConformance, QualityStatus
from app.operations.models.facilities import WorkOrder

TENANT = "tenant_acme"  # demo tenant — matches seed_demo_user and dev-mode tenant

def _id():
    return str(uuid.uuid4())


async def seed_tenant(db, tenant: str = TENANT) -> bool:
    """Seed the full Operations domain for ``tenant`` in the given session.

    Idempotent: if the tenant already has projects, nothing is touched and
    False is returned. Returns True when a fresh seed ran.
    """
    already = (await db.execute(
        select(Project.id).where(Project.tenant_id == tenant).limit(1)
    )).scalar_one_or_none()
    if already is not None:
        print(f"[SKIP] Operations already seeded for {tenant}; leaving existing data untouched.")
        return False

    now = datetime.now(timezone.utc)

    # 1. Ops Team Members
    ops_staff = [
        OpsTeamMember(id=_id(), tenant_id=tenant, name="Dwight Schrute", role="Facilities Director", email="dwight.ops@kaeos.io", is_active=True),
        OpsTeamMember(id=_id(), tenant_id=tenant, name="Angela Martin", role="Procurement Head", email="angela.ops@kaeos.io", is_active=True),
        OpsTeamMember(id=_id(), tenant_id=tenant, name="Oscar Martinez", role="Program Manager", email="oscar.ops@kaeos.io", is_active=True)
    ]
    for s in ops_staff:
        db.add(s)
    await db.flush()

    # 2. Department Configs
    configs = [
        DepartmentConfig(id=_id(), tenant_id=tenant, department_slug="hr", auto_approval_limit=500.00, audit_frequency_days=90),
        DepartmentConfig(id=_id(), tenant_id=tenant, department_slug="finance", auto_approval_limit=5000.00, audit_frequency_days=30),
        DepartmentConfig(id=_id(), tenant_id=tenant, department_slug="support", auto_approval_limit=250.00, audit_frequency_days=180)
    ]
    for cfg in configs:
        db.add(cfg)
    await db.flush()

    # 3. Projects & Milestones
    projects = [
        Project(id=_id(), tenant_id=tenant, name="KAEOS Core Node Expansion v3", description="Scaling cluster operations and provisioning multi-region DB backups.", status=ProjectStatus.ACTIVE, start_date=date.today() - timedelta(days=30), end_date=date.today() + timedelta(days=90), project_manager_id=ops_staff[2].id, completion_percentage=45.00),
        Project(id=_id(), tenant_id=tenant, name="Marketplace SSO Integration", description="Integrating SAML/OIDC single sign-on for corporate domain packs.", status=ProjectStatus.PLANNING, start_date=None, end_date=None, completion_percentage=0.00)
    ]
    for prj in projects:
        db.add(prj)
    await db.flush()

    milestones = [
        Milestone(id=_id(), tenant_id=tenant, project_id=projects[0].id, name="Backups Verification", target_date=date.today() + timedelta(days=15), status="PENDING"),
        Milestone(id=_id(), tenant_id=tenant, project_id=projects[0].id, name="Docker Registry Migration", target_date=date.today() - timedelta(days=10), status="ACHIEVED")
    ]
    for mil in milestones:
        db.add(mil)
    await db.flush()

    # 4. Tasks (+ dependencies: infra must be provisioned before regression
    # testing can run, and the debate-node deploy waits on that testing —
    # a real critical-path chain, not three unrelated rows).
    tasks = [
        Task(id=_id(), tenant_id=tenant, project_id=projects[0].id, task_name="Provision AWS S3 Buckets in Dublin region", assigned_to="SRE Lead", due_date=date.today() + timedelta(days=5), status="IN_PROGRESS"),
        Task(id=_id(), tenant_id=tenant, project_id=projects[0].id, task_name="Regression testing of peer-agent debate channels", assigned_to="QA Analyst", due_date=date.today() - timedelta(days=2), status="TODO", ai_risk_assessment="WARNING: Task is overdue and blocks deployment of debate nodes."),
        Task(id=_id(), tenant_id=tenant, project_id=projects[0].id, task_name="Deploy debate node cluster to Dublin region", assigned_to="SRE Lead", due_date=date.today() + timedelta(days=12), status="TODO"),
    ]
    for tsk in tasks:
        db.add(tsk)
    await db.flush()

    task_deps = [
        TaskDependency(id=_id(), tenant_id=tenant, task_id=tasks[1].id, depends_on_task_id=tasks[0].id),
        TaskDependency(id=_id(), tenant_id=tenant, task_id=tasks[2].id, depends_on_task_id=tasks[1].id),
    ]
    for dep in task_deps:
        db.add(dep)

    # 5. Resources & Allocations
    resources = [
        Resource(id=_id(), tenant_id=tenant, name="AWS Ireland Cluster", resource_type="SERVER", cost_per_hour=1.25),
        Resource(id=_id(), tenant_id=tenant, name="Senior QA Engineer", resource_type="DEVELOPER", cost_per_hour=75.00),
    ]
    for res in resources:
        db.add(res)
    await db.flush()

    allocations = [
        ResourceAllocation(id=_id(), tenant_id=tenant, resource_id=resources[1].id, project_id=projects[0].id, allocated_hours=45.00, utilization_percentage=112.50),
        ResourceAllocation(id=_id(), tenant_id=tenant, resource_id=resources[0].id, project_id=projects[0].id, allocated_hours=168.00, utilization_percentage=100.00),
    ]
    for alloc in allocations:
        db.add(alloc)

    # Capacity plans
    plan = CapacityPlan(id=_id(), tenant_id=tenant, quarter="Q3-2026", headcount_requested=2, estimated_budget=150000.00)
    db.add(plan)

    # 6. Vendor contracts & performance
    vendors = [
        VendorContract(id=_id(), tenant_id=tenant, vendor_name="Dublin Cloud Hosting Services", service_provided="Server Infrastructure backups storage", contract_value=45000.00, renewal_date=date.today() + timedelta(days=180), owner_id=ops_staff[2].id),
    ]
    for v in vendors:
        db.add(v)
    await db.flush()

    perf = VendorPerformance(id=_id(), tenant_id=tenant, vendor_contract_id=vendors[0].id, delivery_rating=95.00, sla_compliance_score=98.00, overall_performance_score=96.50)
    db.add(perf)

    # 7. Procurement Purchase Requests
    requests = [
        PurchaseRequest(id=_id(), tenant_id=tenant, item_description="10x Apple MacBook Pro 14 (M3)", quantity=10, unit_price=1999.00, total_estimated_cost=19990.00, status=ProcurementStatus.PENDING_APPROVAL, requested_by="IT Lead", department="Platform"),
        PurchaseRequest(id=_id(), tenant_id=tenant, item_description="Generic developer desk chairs", quantity=3, unit_price=299.00, total_estimated_cost=897.00, status=ProcurementStatus.APPROVED, requested_by="Facilities Clerk", department="Support"),
    ]
    for req in requests:
        db.add(req)
    await db.flush()

    # vendor_id stays NULL: "OfficeMax Business" has no fin_vendors master,
    # and an unmatched PO is left unlinked rather than mis-joined.
    po = PurchaseOrder(id=_id(), tenant_id=tenant, purchase_request_id=requests[1].id, po_number="PO-2026-9012", vendor_name="OfficeMax Business", total_amount=897.00, status=ProcurementStatus.RECEIVED)
    db.add(po)
    await db.flush()

    po_line = POLineItem(id=_id(), tenant_id=tenant, purchase_order_id=po.id, line_number=1, description="Generic developer desk chairs", quantity=3, unit_price=299.00, amount=897.00)
    db.add(po_line)
    await db.flush()

    receipt = GoodsReceipt(id=_id(), tenant_id=tenant, purchase_order_id=po.id, po_line_item_id=po_line.id, receiver_name="Dwight Schrute", received_quantity=3, is_damaged=False, status="SUCCESS")
    db.add(receipt)

    # 8. Quality standards & Inspections
    standards = [
        QualityStandard(id=_id(), tenant_id=tenant, name="ISO-9001 Section 8 Operations", description="Operational planning and control standards including design changes verification.", regulatory_framework="ISO-9001"),
    ]
    for std in standards:
        db.add(std)
    await db.flush()

    inspections = [
        Inspection(id=_id(), tenant_id=tenant, standard_id=standards[0].id, inspected_item="Dublin Server backup automation script", inspector="Oscar Martinez", status=QualityStatus.FAILED, notes="Backup script succeeded on tables but failed to record compliance metadata logs."),
    ]
    for insp in inspections:
        db.add(insp)
    await db.flush()

    conformance = NonConformance(
        id=_id(), tenant_id=tenant, inspection_id=inspections[0].id,
        defect_description="Failure to write ROPA audit logs upon server backup execution.",
        impact_rating="HIGH", corrective_action_plan="Add metadata logger to standard backup helper function."
    )
    db.add(conformance)

    # 9. Facility work orders — one per ITGC control category, spanning a
    # clean pass and a real violation so CHANGE_MANAGEMENT / INCIDENT_POSTMORTEM
    # / BACKUP_RETENTION each have genuine data to evaluate when triaged.
    work_orders = [
        # MAINTENANCE -> CHANGE_MANAGEMENT: distinct approver + linked ticket (passes).
        WorkOrder(id=_id(), tenant_id=tenant, facility_name="Dublin Datacenter - Rack 12",
                 issue_title="Replace failing UPS battery bank",
                 description="UPS bank B has degraded runtime below 8 minutes; scheduled replacement window.",
                 category="MAINTENANCE", severity="MEDIUM", status="IN_PROGRESS",
                 is_production=True, implementer="dave.sre@kaeos.io", approver="dwight.ops@kaeos.io",
                 change_ticket="CHG-4471", reported_by="Dwight Schrute"),
        # MAINTENANCE -> CHANGE_MANAGEMENT: self-approved, no ticket (blocks).
        WorkOrder(id=_id(), tenant_id=tenant, facility_name="AWS Ireland Cluster",
                 issue_title="Rotate TLS certificate on primary load balancer",
                 description="Certificate expires in 5 days; needs rotation on the production LB.",
                 category="MAINTENANCE", severity="HIGH", status="OPEN",
                 is_production=True, implementer="oscar.ops@kaeos.io", approver="oscar.ops@kaeos.io",
                 reported_by="Oscar Martinez"),
        # SAFETY -> INCIDENT_POSTMORTEM: resolved SEV2 with a complete postmortem (passes).
        WorkOrder(id=_id(), tenant_id=tenant, facility_name="Dublin Datacenter - Floor 2",
                 issue_title="Electrical short in cooling unit triggered alarm",
                 description="Cooling unit 4 tripped a breaker; no fire, HVAC failover engaged automatically.",
                 category="SAFETY", severity="SEV2", status="RESOLVED",
                 root_cause="Corroded terminal block on cooling unit 4's primary breaker.",
                 action_items="Replace terminal block\nAdd quarterly electrical inspection to the PM schedule",
                 reported_by="Dwight Schrute", resolved_at=now - timedelta(days=2)),
        # SAFETY -> still open: safety keyword forces URGENT triage regardless
        # of severity label; postmortem control is NOT_APPLICABLE until closed.
        WorkOrder(id=_id(), tenant_id=tenant, facility_name="AWS Ireland Cluster - Generator Room",
                 issue_title="Suspected gas leak near backup generator",
                 description="Facilities technician reported a gas odor near the diesel backup generator.",
                 category="SAFETY", severity="CRITICAL", status="OPEN",
                 reported_by="Angela Martin"),
        # DECOMMISSION -> BACKUP_RETENTION: verified backup, past the retention window (passes).
        WorkOrder(id=_id(), tenant_id=tenant, facility_name="Legacy File Server FS-03",
                 issue_title="Decommission end-of-life file server",
                 description="FS-03 reached end of vendor support; workloads migrated to the Dublin cluster.",
                 category="DECOMMISSION", severity="LOW", status="OPEN",
                 backup_verified=True, record_age_days=920, retention_days=365,
                 reported_by="Oscar Martinez"),
    ]
    for wo in work_orders:
        db.add(wo)

    await db.commit()
    print(f"[SUCCESS] Seeded Operations database for {tenant}:")
    print(f"   - {len(ops_staff)} ops staff")
    print(f"   - {len(projects)} projects, {len(tasks)} tasks, {len(task_deps)} task dependencies")
    print(f"   - {len(requests)} purchase requests")
    print(f"   - {len(inspections)} inspections, {len(standards)} standards")
    print(f"   - {len(work_orders)} facility work orders")
    return True


async def seed():
    # Ensure tables are built
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as db:
        await seed_tenant(db)

    # Procurement is a first-class department over these same ops_ tables. It has
    # no separate sentinel table, so seed its comprehensive source-to-pay
    # governance scenarios here (after the ops session closes - it opens its own).
    # Idempotent on its own sentinel, so it is always safe to call.
    from app.procurement.seed import seed as _seed_procurement
    await _seed_procurement()


if __name__ == "__main__":
    asyncio.run(seed())
