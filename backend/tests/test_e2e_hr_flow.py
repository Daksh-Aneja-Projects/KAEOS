"""End-to-end flow on the zero-dependency dev stack (SQLite + simulated LLM):

    deploy department  ->  create requisition + candidate  ->  gated AI screening
    (7-gate pipeline)  ->  provenance record written  ->  HITL resolution wiring.

This drives the backend services directly against a single shared in-memory engine
(the deployment pipeline runs on AsyncSessionLocal, so we use that everywhere here
rather than the HTTP get_db override) with no external services required.
"""
import pytest

# Force the fast, deterministic simulated LLM path (no provider) for the whole run.
from app.services.llm_router import LLMRouter
LLMRouter.provider_available = lambda self, *a, **k: False


@pytest.mark.asyncio
async def test_e2e_deploy_screen_gate_provenance_hitl():
    from sqlalchemy import select
    from app.core.database import init_db, AsyncSessionLocal
    from app.workforce.domain_packs.engine import DomainPackEngine
    from app.workforce.models.domain_pack import DomainPack
    from app.workforce.deployment.state_machine import DeploymentStateMachine
    from app.workforce.deployment.studio import DeploymentStudio
    from app.workforce.models.core import (
        WorkforceDeployment, DeploymentStatus, DepartmentAgent,
    )
    from app.hr.models.recruiting import JobRequisition, Candidate, CandidateStage, ReqStatus
    from app.hr.agents.recruiting_agent import RecruitingAgent
    from app.models.domain import SkillExecution
    from app.services.hitl_manager import hitl_manager

    tenant = "tenant-e2e"
    await init_db()

    # ── 1. Seed the built-in HR domain pack ──────────────────────────────────
    async with AsyncSessionLocal() as db:
        await DomainPackEngine.sync_built_in_packs(db)
        pack = (await db.execute(select(DomainPack).where(DomainPack.slug == "hr"))).scalar_one()
        pack_id = pack.id

    # ── 2. Deploy the department through the real FSM pipeline ────────────────
    async with AsyncSessionLocal() as db:
        deployment = await DeploymentStateMachine.create_deployment(
            db, tenant, pack_id,
            {"capabilities": [], "systems": [], "employee_count": 25},
        )
        deployment_id = deployment.id

    # Run the single-owner pipeline directly (await instead of background task).
    await DeploymentStudio._run_deployment_pipeline(tenant, deployment_id, {})

    async with AsyncSessionLocal() as db:
        dep = (await db.execute(
            select(WorkforceDeployment).where(WorkforceDeployment.id == deployment_id)
        )).scalar_one()
        assert dep.status == DeploymentStatus.ACTIVE, f"deployment not active: {dep.status}"
        assert dep.department_id, "no department created"

        agents = (await db.execute(
            select(DepartmentAgent).where(DepartmentAgent.department_id == dep.department_id)
        )).scalars().all()
        assert len(agents) > 0, "no agents deployed"

    # ── 3. Create a requisition + candidate ──────────────────────────────────
    async with AsyncSessionLocal() as db:
        req = JobRequisition(
            tenant_id=tenant, title="Platform Engineer", department="Engineering",
            hiring_manager_id="mgr-e2e", job_description="Build the platform.",
            requirements=["Python", "Distributed systems"], status=ReqStatus.OPEN,
        )
        db.add(req)
        await db.commit()
        await db.refresh(req)

        cand = Candidate(
            tenant_id=tenant, requisition_id=req.id,
            first_name="Grace", last_name="Hopper", email="grace@example.com",
            stage=CandidateStage.APPLIED,
        )
        db.add(cand)
        await db.commit()
        await db.refresh(cand)
        candidate_id = cand.id

    # ── 4. Gated AI screening through the 7-gate AgentExecutor ────────────────
    async with AsyncSessionLocal() as db:
        agent = RecruitingAgent()
        result = await agent.screen_candidate(db, candidate_id)

    # The pipeline either completed cleanly or a gate intervened — both carry an
    # execution id we can trace. A clean run returns the evaluation + execution_id.
    execution_id = result.get("execution_id") or (result.get("detail") or {}).get("execution_id")
    assert execution_id, f"no provenance/execution reference returned: {result}"

    # ── 5. Provenance: a SkillExecution record was written for this run ───────
    async with AsyncSessionLocal() as db:
        rec = (await db.execute(
            select(SkillExecution).where(SkillExecution.id == execution_id)
        )).scalar_one_or_none()
        assert rec is not None, "no SkillExecution provenance record persisted"
        assert rec.tenant_id == tenant
        assert rec.skill_id_name == "hr_recruitment_screening"

    # ── 6. HITL wiring: resolving a non-pending execution reports 'not found' ──
    # (Proves the HITL resolution path is wired; without Redis and with no pending
    # approval, resolve_hitl returns False rather than raising.)
    resolved = await hitl_manager.resolve_hitl("no-such-exec", approved=True)
    assert resolved is False
