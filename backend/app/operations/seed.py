"""
KAEOS Operations Domain — Database Seed Script
Seeds the Operations tables with projects, team allocations, purchase requests,
and quality standards.
"""
import asyncio
import uuid
from datetime import date, timedelta

from app.core.database import async_engine, AsyncSessionLocal
from app.models.domain import Base

# Models imports
from app.operations.models.core import OpsTeamMember, DepartmentConfig
from app.operations.models.projects import Project, Milestone, Task, ProjectStatus
from app.operations.models.resources import Resource, ResourceAllocation, CapacityPlan
from app.operations.models.vendors import VendorContract, VendorPerformance
from app.operations.models.procurement import PurchaseRequest, PurchaseOrder, GoodsReceipt, ProcurementStatus
from app.operations.models.quality import QualityStandard, Inspection, NonConformance, QualityStatus

TENANT = "tenant_acme"  # demo tenant — matches seed_demo_user and dev-mode tenant

def _id():
    return str(uuid.uuid4())

async def seed():
    # Ensure tables are built
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as db:
        # 1. Ops Team Members
        ops_staff = [
            OpsTeamMember(id=_id(), tenant_id=TENANT, name="Dwight Schrute", role="Facilities Director", email="dwight.ops@kaeos.io", is_active=True),
            OpsTeamMember(id=_id(), tenant_id=TENANT, name="Angela Martin", role="Procurement Head", email="angela.ops@kaeos.io", is_active=True),
            OpsTeamMember(id=_id(), tenant_id=TENANT, name="Oscar Martinez", role="Program Manager", email="oscar.ops@kaeos.io", is_active=True)
        ]
        for s in ops_staff:
            db.add(s)
        await db.flush()

        # 2. Department Configs
        configs = [
            DepartmentConfig(id=_id(), tenant_id=TENANT, department_slug="hr", auto_approval_limit=500.00, audit_frequency_days=90),
            DepartmentConfig(id=_id(), tenant_id=TENANT, department_slug="finance", auto_approval_limit=5000.00, audit_frequency_days=30),
            DepartmentConfig(id=_id(), tenant_id=TENANT, department_slug="support", auto_approval_limit=250.00, audit_frequency_days=180)
        ]
        for cfg in configs:
            db.add(cfg)
        await db.flush()

        # 3. Projects & Milestones
        projects = [
            Project(id=_id(), tenant_id=TENANT, name="KAEOS Core Node Expansion v3", description="Scaling cluster operations and provisioning multi-region DB backups.", status=ProjectStatus.ACTIVE, start_date=date.today() - timedelta(days=30), end_date=date.today() + timedelta(days=90), project_manager_id=ops_staff[2].id, completion_percentage=45.00),
            Project(id=_id(), tenant_id=TENANT, name="Marketplace SSO Integration", description="Integrating SAML/OIDC single sign-on for corporate domain packs.", status=ProjectStatus.PLANNING, start_date=None, end_date=None, completion_percentage=0.00)
        ]
        for prj in projects:
            db.add(prj)
        await db.flush()

        milestones = [
            Milestone(id=_id(), tenant_id=TENANT, project_id=projects[0].id, name="Backups Verification", target_date=date.today() + timedelta(days=15), status="PENDING"),
            Milestone(id=_id(), tenant_id=TENANT, project_id=projects[0].id, name="Docker Registry Migration", target_date=date.today() - timedelta(days=10), status="ACHIEVED")
        ]
        for mil in milestones:
            db.add(mil)
        await db.flush()

        # 4. Tasks
        tasks = [
            Task(id=_id(), tenant_id=TENANT, project_id=projects[0].id, task_name="Provision AWS S3 Buckets in Dublin region", assigned_to="SRE Lead", due_date=date.today() + timedelta(days=5), status="IN_PROGRESS"),
            Task(id=_id(), tenant_id=TENANT, project_id=projects[0].id, task_name="Regression testing of peer-agent debate channels", assigned_to="QA Analyst", due_date=date.today() - timedelta(days=2), status="TODO", ai_risk_assessment="WARNING: Task is overdue and blocks deployment of debate nodes."),
        ]
        for tsk in tasks:
            db.add(tsk)
        await db.flush()

        # 5. Resources & Allocations
        resources = [
            Resource(id=_id(), tenant_id=TENANT, name="AWS Ireland Cluster", resource_type="SERVER", cost_per_hour=1.25),
            Resource(id=_id(), tenant_id=TENANT, name="Senior QA Engineer", resource_type="DEVELOPER", cost_per_hour=75.00),
        ]
        for res in resources:
            db.add(res)
        await db.flush()

        allocations = [
            ResourceAllocation(id=_id(), tenant_id=TENANT, resource_id=resources[1].id, project_id=projects[0].id, allocated_hours=45.00, utilization_percentage=112.50),
            ResourceAllocation(id=_id(), tenant_id=TENANT, resource_id=resources[0].id, project_id=projects[0].id, allocated_hours=168.00, utilization_percentage=100.00),
        ]
        for alloc in allocations:
            db.add(alloc)

        # Capacity plans
        plan = CapacityPlan(id=_id(), tenant_id=TENANT, quarter="Q3-2026", headcount_requested=2, estimated_budget=150000.00)
        db.add(plan)

        # 6. Vendor contracts & performance
        vendors = [
            VendorContract(id=_id(), tenant_id=TENANT, vendor_name="Dublin Cloud Hosting Services", service_provided="Server Infrastructure backups storage", contract_value=45000.00, renewal_date=date.today() + timedelta(days=180), owner_id=ops_staff[2].id),
        ]
        for v in vendors:
            db.add(v)
        await db.flush()

        perf = VendorPerformance(id=_id(), tenant_id=TENANT, vendor_contract_id=vendors[0].id, delivery_rating=95.00, sla_compliance_score=98.00, overall_performance_score=96.50)
        db.add(perf)

        # 7. Procurement Purchase Requests
        requests = [
            PurchaseRequest(id=_id(), tenant_id=TENANT, item_description="10x Apple MacBook Pro 14 (M3)", quantity=10, unit_price=1999.00, total_estimated_cost=19990.00, status=ProcurementStatus.PENDING_APPROVAL, requested_by="IT Lead", department="Platform"),
            PurchaseRequest(id=_id(), tenant_id=TENANT, item_description="Generic developer desk chairs", quantity=3, unit_price=299.00, total_estimated_cost=897.00, status=ProcurementStatus.APPROVED, requested_by="Facilities Clerk", department="Support"),
        ]
        for req in requests:
            db.add(req)
        await db.flush()

        po = PurchaseOrder(id=_id(), tenant_id=TENANT, purchase_request_id=requests[1].id, po_number="PO-2026-9012", vendor_name="OfficeMax Business", total_amount=897.00, status=ProcurementStatus.APPROVED)
        db.add(po)
        await db.flush()

        receipt = GoodsReceipt(id=_id(), tenant_id=TENANT, purchase_order_id=po.id, receiver_name="Dwight Schrute", received_quantity=3, is_damaged=False, status="SUCCESS")
        db.add(receipt)

        # 8. Quality standards & Inspections
        standards = [
            QualityStandard(id=_id(), tenant_id=TENANT, name="ISO-9001 Section 8 Operations", description="Operational planning and control standards including design changes verification.", regulatory_framework="ISO-9001"),
        ]
        for std in standards:
            db.add(std)
        await db.flush()

        inspections = [
            Inspection(id=_id(), tenant_id=TENANT, standard_id=standards[0].id, inspected_item="Dublin Server backup automation script", inspector="Oscar Martinez", status=QualityStatus.FAILED, notes="Backup script succeeded on tables but failed to record compliance metadata logs."),
        ]
        for insp in inspections:
            db.add(insp)
        await db.flush()

        conformance = NonConformance(
            id=_id(), tenant_id=TENANT, inspection_id=inspections[0].id,
            defect_description="Failure to write ROPA audit logs upon server backup execution.",
            impact_rating="HIGH", corrective_action_plan="Add metadata logger to standard backup helper function."
        )
        db.add(conformance)

        await db.commit()
        print("[SUCCESS] Seeded Operations database:")
        print(f"   - {len(ops_staff)} ops staff")
        print(f"   - {len(projects)} projects")
        print(f"   - {len(tasks)} tasks")
        print(f"   - {len(requests)} purchase requests")
        print(f"   - {len(inspections)} inspections, {len(standards)} standards")

if __name__ == "__main__":
    asyncio.run(seed())
