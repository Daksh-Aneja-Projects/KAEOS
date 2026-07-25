"""
KAEOS - seed the workforce backbone (Capability -> Process -> DepartmentAgent)
for a tenant whose departments already exist (e.g. created by onboarding).

The normal path is a WorkforceDeployment run through the async job queue, but a
department created by onboarding is *adopted* by the generator, which - before
the adoption fix - skipped capability/process/agent creation. This script runs
the (now idempotent) generator directly on the OWNER connection (RLS-exempt), so
each existing department gets its full backbone bound to the matching domain
pack. Safe to re-run: every step is idempotent.

    python -m scripts.seed_workforce_backbone --tenant tenant_acme
"""
import argparse
import asyncio
import logging

from sqlalchemy import select

from app.core.database import MaintenanceSessionLocal

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("seed_backbone")


async def seed(tenant_id: str) -> None:
    from app.workforce.models.core import (
        Department, Capability, BusinessProcess, DepartmentAgent, DeploymentStatus,
    )
    from app.workforce.models.domain_pack import DomainPack
    from app.workforce.deployment.state_machine import DeploymentStateMachine
    from app.workforce.orchestration.workforce_generator import WorkforceGenerator

    generator = WorkforceGenerator()

    async with MaintenanceSessionLocal() as db:
        depts = (await db.execute(
            select(Department).where(Department.tenant_id == tenant_id)
        )).scalars().all()
        packs = {p.slug: p for p in (await db.execute(select(DomainPack))).scalars().all()}

        logger.info("Tenant %s: %d departments, %d packs", tenant_id, len(depts), len(packs))

        for dept in sorted(depts, key=lambda d: d.slug):
            pack = packs.get(dept.slug)
            if not pack:
                logger.warning("  %-12s no matching domain pack - skipping", dept.slug)
                continue

            # A fresh deployment record ties the generated backbone to this run.
            deployment = await DeploymentStateMachine.create_deployment(
                db, tenant_id, pack.id,
                {"capabilities": [], "systems": [], "employee_count": dept.employee_count or 50},
            )

            # 1. Structure: adopts the existing department, creates missing caps/procs.
            adopted = await generator.generate_department_structure(db, tenant_id, deployment.id)
            # 2. Agents: binds pack agent definitions to each capability.
            await generator.deploy_agents(db, tenant_id, deployment.id, adopted.id)

            deployment.status = DeploymentStatus.ACTIVE
            db.add(deployment)
            await db.commit()

            caps = len((await db.execute(
                select(Capability).where(Capability.department_id == adopted.id)
            )).scalars().all())
            procs = len((await db.execute(
                select(BusinessProcess).where(BusinessProcess.department_id == adopted.id)
            )).scalars().all())
            agents = len((await db.execute(
                select(DepartmentAgent).where(DepartmentAgent.department_id == adopted.id)
            )).scalars().all())
            logger.info("  %-12s caps=%-2d procs=%-2d agents=%-2d", dept.slug, caps, procs, agents)

    logger.info("Done.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--tenant", default="tenant_acme")
    args = ap.parse_args()
    asyncio.run(seed(args.tenant))
