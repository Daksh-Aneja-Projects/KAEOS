"""
KAEOS — Master Seed Orchestrator
Runs ALL domain seeders in the correct order, ensuring cross-domain consistency.
Usage: cd backend && python -m scripts.seed_master
"""
import asyncio
import logging
import sys
import os
import time

# Ensure the backend directory is on the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("seed_master")


async def run_all_seeds():
    start = time.time()
    logger.info("=" * 70)
    logger.info("KAEOS MASTER SEEDER — Comprehensive Data Population")
    logger.info("=" * 70)

    # Phase 0: Initialize database tables
    logger.info("\n[Phase 0] Initializing database tables...")
    from app.core.database import init_db
    await init_db()
    logger.info("[Phase 0] Database tables initialized ✓")

    # Phase 1: Core seed (rules, skills, employees, connectors, etc.)
    logger.info("\n[Phase 1] Core Knowledge Base seed...")
    from app.core.database import AsyncSessionLocal
    from app.core.seed import seed_database
    async with AsyncSessionLocal() as session:
        seeded = await seed_database(session)
        if seeded:
            logger.info("[Phase 1] Core KB seeded (rules, skills, employees, connectors, conflicts, marketplace) ✓")
        else:
            logger.info("[Phase 1] Core KB already seeded — skipping ✓")

    # Phase 1b: Demo auth user
    logger.info("\n[Phase 1b] Demo auth user...")
    async with AsyncSessionLocal() as session:
        from app.services.auth import AuthService
        await AuthService.seed_demo_user(session)
    logger.info("[Phase 1b] Demo user seeded ✓")

    # Phase 2: Department domains (HR, Finance, Legal, Sales, Support, Operations)
    logger.info("\n[Phase 2] Domain-specific seeds...")
    from app.core.domain_seed import seed_domains_if_empty
    await seed_domains_if_empty()
    logger.info("[Phase 2] All 6 domain seeds completed ✓")

    # Phase 3: Workforce layer (domain packs, departments)
    logger.info("\n[Phase 3] Workforce domain packs...")
    try:
        async with AsyncSessionLocal() as session:
            from app.workforce.domain_packs.engine import DomainPackEngine
            await DomainPackEngine.sync_built_in_packs(session)
        logger.info("[Phase 3] Built-in domain packs synced ✓")
    except Exception as e:
        logger.warning(f"[Phase 3] Domain pack sync failed (non-fatal): {e}")

    # Phase 4: Agent Factory (blueprints, deployed agents, debates, feed)
    logger.info("\n[Phase 4] Agent Factory seed...")
    try:
        from scripts.seed_agent_factory import seed as seed_agent_factory
        await seed_agent_factory()
        logger.info("[Phase 4] Agent Factory seeded ✓")
    except Exception as e:
        logger.warning(f"[Phase 4] Agent Factory seed failed (non-fatal): {e}")

    # Phase 5: External Intelligence & Integrations (signals, candidate rules)
    logger.info("\n[Phase 5] External Intelligence & Integrations seed...")
    try:
        from scripts.seed_integrations import seed as seed_integrations
        await seed_integrations()
        logger.info("[Phase 5] Integrations seeded ✓")
    except Exception as e:
        logger.warning(f"[Phase 5] Integrations seed failed (non-fatal): {e}")

    # Phase 6: Infrastructure Layer (models, costs, agents, onboarding)
    logger.info("\n[Phase 6] Infrastructure Layer seed...")
    try:
        from scripts.seed_infrastructure import seed as seed_infrastructure
        await seed_infrastructure()
        logger.info("[Phase 6] Infrastructure seeded ✓")
    except Exception as e:
        logger.warning(f"[Phase 6] Infrastructure seed failed (non-fatal): {e}")

    # Phase 7: Department metric rollup
    logger.info("\n[Phase 7] Rolling up department metrics from real data...")
    try:
        from app.core.domain_seed import rollup_department_metrics
        await rollup_department_metrics()
        logger.info("[Phase 7] Department metrics rolled up ✓")
    except Exception as e:
        logger.warning(f"[Phase 7] Metric rollup failed (non-fatal): {e}")

    elapsed = time.time() - start
    logger.info("\n" + "=" * 70)
    logger.info(f"KAEOS MASTER SEEDER COMPLETE — {elapsed:.1f}s total")
    logger.info("=" * 70)
    logger.info("All frontend pages should now render with live data from DB.")
    logger.info("Start backend: uvicorn app.main:app --port 8001 --reload")
    logger.info("Start frontend: cd ../frontend && npm run dev")


if __name__ == "__main__":
    asyncio.run(run_all_seeds())
