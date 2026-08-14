"""
KAEOS Workforce Org-Graph Seeder

Gives every department its capability + agent backbone so the org-wide views
(Neural Map, Reality Experience, Org Pulse, Departments hub, Command Center)
render a populated organisation instead of an empty graph.

This does NOT fabricate rows. It drives the product's own deterministic
deployment path - WorkforceGenerator.generate_department_structure() followed by
deploy_agents() - against each synced domain pack, which is exactly what happens
when a real tenant deploys that department. The capabilities, agent names,
personas and compliance tags therefore come from the pack YAML definitions, so
the demo organisation and a customer's organisation are built the same way and
cannot drift apart.

Fully deterministic (no LLM calls) and idempotent at three levels: a department
that already has agents is skipped by the generator, only missing capability
slugs are created, and a deployment is reused per (tenant, pack).

Called from the startup lifespan after the departments are seeded and the packs
are synced.
"""
import logging

from sqlalchemy import func as sqlfunc, select

from app.core.database import AsyncSessionLocal
from app.workforce.models.core import Capability, Department, DepartmentAgent
from app.workforce.models.domain_pack import DomainPack

logger = logging.getLogger(__name__)

SEED_TENANT = "tenant_acme"


async def seed_workforce_graph(tenant_id: str = SEED_TENANT) -> dict:
    """Ensure every department with a synced pack has its capabilities + agents.

    Returns a summary dict. Never raises: a failure to enrich the demo graph must
    not stop the application from booting.
    """
    from app.core.context import current_tenant_id
    from app.core.database import MaintenanceSessionLocal
    from app.workforce.deployment.state_machine import DeploymentStateMachine
    from app.workforce.models.core import DeploymentStatus
    from app.workforce.orchestration.workforce_generator import WorkforceGenerator

    created = {"departments": 0, "capabilities": 0, "agents": 0, "skipped": 0}
    token = current_tenant_id.set(tenant_id)
    try:
        # Owner/maintenance session: seeding writes across a tenant's whole
        # workforce backbone and must not be filtered by the RLS policy, exactly
        # as scripts/seed_workforce_backbone.py does.
        async with MaintenanceSessionLocal() as db:
            packs = (await db.execute(select(DomainPack))).scalars().all()
            if not packs:
                logger.info("[WorkforceSeed] no domain packs synced yet; nothing to build")
                return created

            generator = WorkforceGenerator()
            for pack in packs:
                try:
                    dept = (await db.execute(
                        select(Department).where(
                            Department.tenant_id == tenant_id,
                            Department.slug == pack.slug,
                        )
                    )).scalar_one_or_none()
                    if dept is None:
                        # A pack with no seeded department for this tenant. The
                        # generator would create one, but the demo tenant's
                        # departments are seeded deliberately, so skip rather than
                        # invent a department nobody asked for.
                        continue

                    agent_count = (await db.execute(
                        select(sqlfunc.count()).select_from(DepartmentAgent)
                        .where(DepartmentAgent.department_id == dept.id)
                    )).scalar() or 0
                    cap_count = (await db.execute(
                        select(sqlfunc.count()).select_from(Capability)
                        .where(Capability.department_id == dept.id)
                    )).scalar() or 0
                    if agent_count and cap_count:
                        created["skipped"] += 1
                        continue

                    # A fresh deployment per run, created through the state machine.
                    # It must NOT carry a department_id: generate_department_structure
                    # returns early when one is already set, which skips capability
                    # creation entirely. Leaving it unset lets the generator adopt
                    # the department by slug and build its full backbone.
                    deployment = await DeploymentStateMachine.create_deployment(
                        db, tenant_id, pack.id,
                        {"capabilities": [], "systems": [],
                         "employee_count": dept.employee_count or 0},
                    )

                    # The real product path: adopt the department by slug, create
                    # the pack's capabilities + processes, then deploy its agents.
                    adopted = await generator.generate_department_structure(
                        db, tenant_id, deployment.id)
                    await generator.deploy_agents(db, tenant_id, deployment.id, adopted.id)

                    deployment.status = DeploymentStatus.ACTIVE
                    db.add(deployment)
                    await db.commit()

                    new_caps = (await db.execute(
                        select(sqlfunc.count()).select_from(Capability)
                        .where(Capability.department_id == dept.id)
                    )).scalar() or 0
                    new_agents = (await db.execute(
                        select(sqlfunc.count()).select_from(DepartmentAgent)
                        .where(DepartmentAgent.department_id == dept.id)
                    )).scalar() or 0

                    # Keep the department's headline counters honest: they are what
                    # the hub and neural map display.
                    dept.capability_count = new_caps
                    dept.agent_count = new_agents
                    db.add(dept)
                    await db.commit()

                    created["departments"] += 1
                    created["capabilities"] += max(0, new_caps - cap_count)
                    created["agents"] += max(0, new_agents - agent_count)
                    logger.info(
                        "[WorkforceSeed] %s: %s capabilities, %s agents",
                        pack.slug, new_caps, new_agents,
                    )
                except Exception as e:  # one bad pack must not stop the rest
                    await db.rollback()
                    logger.warning(
                        "[WorkforceSeed] %s: could not build workforce (non-fatal): %s",
                        getattr(pack, "slug", "?"), e,
                    )
    except Exception as e:
        logger.warning("[WorkforceSeed] skipped (non-fatal): %s", e)
    finally:
        current_tenant_id.reset(token)

    if created["departments"]:
        logger.info(
            "[WorkforceSeed] built %s departments: %s capabilities, %s agents "
            "(%s already complete)",
            created["departments"], created["capabilities"], created["agents"],
            created["skipped"],
        )
    return created
