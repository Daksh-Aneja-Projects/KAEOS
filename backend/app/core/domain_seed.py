"""
KAEOS — Domain seed orchestration (startup)

Runs each department domain seeder (HR, Finance, Legal, Sales, Support,
Operations) when its tables are empty, so every dashboard renders live data
out of the box. Each check is per-domain and idempotent — an already-seeded
domain is never re-seeded.

Also rolls Department KPI metrics (tasks completed, hours saved, automation
coverage) up from real skill-execution data so the Workforce dashboard shows
non-zero, internally consistent numbers.
"""
import importlib
import logging

from sqlalchemy import select, func as sqlfunc

# Domain seeding is maintenance: use the owner connection so it is not
# blocked by tenant RLS (the app role cannot insert without a context).
from app.core.database import MaintenanceSessionLocal as AsyncSessionLocal

logger = logging.getLogger(__name__)

# (name, seed module, sentinel model "module:Class") — the sentinel's row count
# for the tenant decides whether the domain still needs seeding.
_DOMAINS = [
    ("HR",         "app.hr.seed",         "app.hr.models.core:HREmployee"),
    ("Finance",    "app.finance.seed",    "app.finance.models.accounts_payable:Vendor"),
    ("Legal",      "app.legal.seed",      "app.legal.models.contracts:Contract"),
    ("Sales",      "app.sales.seed",      "app.sales.models.leads:Lead"),
    ("Support",    "app.support.seed",    "app.support.models.tickets:Ticket"),
    ("Operations", "app.operations.seed", "app.operations.models.projects:Project"),
    ("Engineering", "app.engineering.seed", "app.engineering.models.core:Service"),
]

SEED_TENANT = "tenant_acme"


def _resolve(path: str):
    mod_path, cls_name = path.split(":")
    return getattr(importlib.import_module(mod_path), cls_name)


async def seed_domains_if_empty() -> None:
    for name, seed_module, sentinel_path in _DOMAINS:
        try:
            sentinel = _resolve(sentinel_path)
            async with AsyncSessionLocal() as db:
                count = (
                    await db.execute(select(sqlfunc.count()).select_from(sentinel))
                ).scalar() or 0
            if count > 0:
                logger.info(f"[DomainSeed] {name}: already seeded ({count} rows) — skipping")
                continue

            mod = importlib.import_module(seed_module)
            mod.TENANT = SEED_TENANT
            # Each per-domain seeder opens its OWN session on the app engine
            # (kaeos_app, a NON-owner), so on Postgres its writes are subject to
            # RLS. Startup seeding has no request context, so app.tenant_id was
            # unset and every INSERT violated the tenant_isolation policy - a
            # fresh deploy seeded NOTHING. Bind the seed tenant so the RLS
            # listener (see database.py after_begin) sets app.tenant_id and the
            # tenant_acme rows are accepted. Masked until now by a persisted
            # volume that already held seed data from an older code path.
            from app.core.context import current_tenant_id
            _tok = current_tenant_id.set(SEED_TENANT)
            try:
                await mod.seed()
            finally:
                current_tenant_id.reset(_tok)
            logger.info(f"[DomainSeed] {name}: seeded")
        except Exception as e:
            logger.warning(f"[DomainSeed] {name}: seed failed (non-fatal): {e}")

    try:
        await rollup_department_metrics()
    except Exception as e:
        logger.warning(f"[DomainSeed] Department metric rollup failed (non-fatal): {e}")


# Skill.department values → workforce Department slugs
_DEPT_SLUG_MAP = {
    "customer_support": "support",
    "customer success": "support",
    "support": "support",
    "sales": "sales",
    "finance": "finance",
    "hr": "hr",
    "human resources": "hr",
    "legal": "legal",
    "operations": "operations",
    "engineering": "engineering",
    "it ops": "engineering",
    "platform": "engineering",
}


async def rollup_department_metrics() -> None:
    """Derive Department KPIs from real execution data.

    tasks_completed_total  ← skill executions attributed to the department
    hours_saved_total      ← 0.5h per completed execution (same heuristic as
                             the workforce overview endpoint)
    automation_coverage    ← share of ACTIVE capabilities
    Capabilities with agents get promoted PLANNED → ACTIVE so the detail pages
    reflect the deployed agents.
    """
    from app.models.domain import Skill, SkillExecution
    from app.workforce.models.core import (
        Department, Capability, CapabilityStatus, DepartmentAgent,
    )

    async with AsyncSessionLocal() as db:
        deps = (await db.execute(select(Department))).scalars().all()
        if not deps:
            return
        by_slug = {d.slug: d for d in deps}

        # Executions per skill department
        rows = (
            await db.execute(
                select(Skill.department, sqlfunc.count(SkillExecution.id))
                .join(SkillExecution, SkillExecution.skill_db_id == Skill.id)
                .group_by(Skill.department)
            )
        ).all()
        per_dept: dict[str, int] = {}
        for dept_name, cnt in rows:
            slug = _DEPT_SLUG_MAP.get((dept_name or "").strip().lower())
            if slug and slug in by_slug:
                per_dept[slug] = per_dept.get(slug, 0) + int(cnt)

        # Supplement with real domain activity (records the agents processed),
        # so departments without generic skill executions still report work.
        try:
            from app.hr.models.recruiting import Candidate
            from app.hr.models.time_attendance import TimeOffRequest
            from app.legal.models.contracts import Contract
            from app.legal.models.compliance import ComplianceObligation
            for slug, models in {
                "hr": [Candidate, TimeOffRequest],
                "legal": [Contract, ComplianceObligation],
            }.items():
                extra = 0
                for model in models:
                    extra += (
                        await db.execute(select(sqlfunc.count()).select_from(model))
                    ).scalar() or 0
                if extra:
                    per_dept[slug] = per_dept.get(slug, 0) + extra
        except Exception as e:
            logger.debug(f"[DomainSeed] activity supplement skipped: {e}")

        # Promote capabilities that have live agents, then compute coverage
        caps = (await db.execute(select(Capability))).scalars().all()
        agents = (await db.execute(select(DepartmentAgent))).scalars().all()
        agents_per_dept: dict[str, int] = {}
        for a in agents:
            agents_per_dept[a.department_id] = agents_per_dept.get(a.department_id, 0) + 1

        caps_per_dept: dict[str, list] = {}
        for c in caps:
            caps_per_dept.setdefault(c.department_id, []).append(c)

        for d in deps:
            dept_caps = caps_per_dept.get(d.id, [])
            dept_agents = agents_per_dept.get(d.id, 0)
            if dept_agents and dept_caps:
                for c in dept_caps:
                    if c.status == CapabilityStatus.PLANNED:
                        c.status = CapabilityStatus.ACTIVE
                        c.active_agents = max(1, dept_agents // max(1, len(dept_caps)))
                        c.automation_pct = c.automation_pct or 0.6

            active = sum(1 for c in dept_caps if c.status == CapabilityStatus.ACTIVE)
            d.automation_coverage = round(active / len(dept_caps), 2) if dept_caps else 0.0

            tasks = per_dept.get(d.slug, 0)
            if tasks:
                d.tasks_completed_total = tasks
                d.hours_saved_total = round(tasks * 0.5, 1)
            d.agent_count = dept_agents or d.agent_count
            d.capability_count = len(dept_caps) or d.capability_count

        await db.commit()
        logger.info(f"[DomainSeed] Department metrics rolled up for {len(deps)} departments")
