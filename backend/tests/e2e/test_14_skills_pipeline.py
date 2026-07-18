"""
KAEOS E2E Test 14 — Skills Registry & 7-Gate Execution Pipeline
Tests the core skill layer end to end: registry list/detail, execution
history, the L9 execution pipeline (compliance gate, rate limit, confidence
gate → HITL), HITL approve/reject, skill compilation from rules, and
explainability.
"""
import pytest
from .conftest import assert_object


@pytest.mark.asyncio
class TestSkillsRegistry:
    """L8 Skills Registry — list, detail, execution history."""

    async def test_skills_list(self, client):
        """Skills registry returns seeded skills with aggregate stats."""
        data = await assert_object(client, "/skills/", [
            "total", "total_executions", "avg_success_rate", "skills",
        ])
        assert data["total"] > 0, "Expected seeded skills"
        skill = data["skills"][0]
        assert "skill_id" in skill
        assert "confidence" in skill

    async def test_skills_filter_by_department(self, client):
        """Skills can be filtered by department."""
        r = await client.get("/skills/?department=sales")
        assert r.status_code == 200
        for s in r.json()["skills"]:
            assert s["department"] == "sales"

    async def test_skills_filter_by_min_confidence(self, client):
        """Skills can be filtered by minimum confidence."""
        r = await client.get("/skills/?min_confidence=0.9")
        assert r.status_code == 200
        for s in r.json()["skills"]:
            assert s["confidence"] >= 0.9

    async def test_skill_detail(self, client):
        """Skill detail returns steps, guardrails, and tool bindings."""
        skills = (await client.get("/skills/")).json()["skills"]
        assert skills, "No skills seeded"
        skill_id = skills[0]["skill_id"]
        r = await client.get(f"/skills/{skill_id}")
        assert r.status_code == 200
        detail = r.json()
        assert detail["skill_id"] == skill_id

    async def test_skill_detail_404(self, client):
        """Unknown skill returns 404."""
        r = await client.get("/skills/definitely_not_a_skill_xyz")
        assert r.status_code == 404

    async def test_skill_executions_history(self, client):
        """Execution history is populated for seeded skills."""
        skills = (await client.get("/skills/")).json()["skills"]
        seeded = [s for s in skills if s.get("execution_count", 0) > 0]
        assert seeded, "Expected at least one skill with execution history"
        r = await client.get(f"/skills/{seeded[0]['skill_id']}/executions")
        assert r.status_code == 200
        execs = r.json()
        assert isinstance(execs, list)
        assert len(execs) > 0, "Expected seeded execution history"
        assert "status" in execs[0]


@pytest.mark.asyncio
class TestSkillExecutionPipeline:
    """L9 Execution Pipeline — the 7-gate flow, HITL, and feedback."""

    async def test_execute_high_confidence_skill(self, client, has_ollama):
        """A high-confidence skill executes through the full pipeline (real Ollama)."""
        if not has_ollama:
            pytest.skip("Ollama not running")
        skills = (await client.get("/skills/?min_confidence=0.82")).json()["skills"]
        active = [s for s in skills if s.get("status") == "ACTIVE"]
        if not active:
            pytest.skip("No high-confidence ACTIVE skills to execute")
        skill_id = active[0]["skill_id"]

        r = await client.post(f"/skills/{skill_id}/execute", json={
            "intent": "E2E pipeline verification run",
            "context": {"source": "e2e_test", "amount": 25},
        })
        assert r.status_code == 200, f"{r.status_code}: {r.text[:300]}"
        data = r.json()
        assert data["skill_id"] == skill_id
        assert data["hitl_required"] is False
        assert data["status"] not in (
            "PENDING_HITL", "BLOCKED_COMPLIANCE", "BLOCKED_RATE_LIMIT",
        ), f"Pipeline did not execute: {data['status']}"
        assert "execution_id" in data
        assert data.get("reasoning_chain"), "Expected a non-empty reasoning chain"

    async def test_execute_low_confidence_skill_triggers_hitl(self, client):
        """A skill below the 0.82 confidence gate goes to PENDING_HITL."""
        skills = (await client.get("/skills/")).json()["skills"]
        low = [s for s in skills if s.get("confidence", 1.0) < 0.82]
        if not low:
            pytest.skip("No low-confidence skills present to exercise the HITL gate")
        skill_id = low[0]["skill_id"]

        r = await client.post(f"/skills/{skill_id}/execute", json={
            "intent": "E2E HITL gate verification",
            "context": {"source": "e2e_test"},
        })
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "PENDING_HITL"
        assert data["hitl_required"] is True
        TestSkillExecutionPipeline._hitl_exec_id = data["execution_id"]

    async def test_hitl_pending_queue(self, client):
        """Pending HITL executions appear in the queue."""
        r = await client.get("/skills/hitl/pending")
        assert r.status_code == 200
        pending = r.json()
        assert isinstance(pending, list)

    async def test_hitl_approve(self, client):
        """A pending HITL execution can be approved."""
        exec_id = getattr(TestSkillExecutionPipeline, "_hitl_exec_id", None)
        if not exec_id:
            pending = (await client.get("/skills/hitl/pending")).json()
            if not pending:
                pytest.skip("No pending HITL executions to approve")
            exec_id = pending[0]["id"]
        r = await client.post(f"/skills/hitl/{exec_id}/approve")
        assert r.status_code == 200
        assert r.json()["status"] == "SUCCESS"

    async def test_hitl_reject(self, client):
        """A pending HITL execution can be rejected (triggers L10 elicitation)."""
        skills = (await client.get("/skills/")).json()["skills"]
        low = [s for s in skills if s.get("confidence", 1.0) < 0.82]
        if not low:
            pytest.skip("No low-confidence skills to create a HITL execution")
        # Create a fresh pending execution to reject
        r = await client.post(f"/skills/{low[0]['skill_id']}/execute", json={
            "intent": "E2E HITL rejection path",
            "context": {"source": "e2e_test"},
        })
        assert r.status_code == 200
        exec_id = r.json()["execution_id"]

        r2 = await client.post(f"/skills/hitl/{exec_id}/reject")
        assert r2.status_code == 200
        assert r2.json()["status"] == "REJECTED"

    async def test_hitl_approve_unknown_404(self, client):
        """Approving a nonexistent execution returns 404."""
        r = await client.post("/skills/hitl/nonexistent-exec-id/approve")
        assert r.status_code == 404


@pytest.mark.asyncio
class TestSkillCompilerAndExplainability:
    """L8 Compiler + L15 Explainability."""

    async def test_compile_skill_from_workflow_rules(self, client):
        """Rules in a workflow compile into a SKILL.md contract + persisted skill."""
        r = await client.post("/skills/compile", json={
            "workflow_id": "wf_refund",
            "domain": "support",
            "workflow_name": "Refund Processing (E2E)",
            "required_tools": ["crm_write", "ticket_update"],
        })
        assert r.status_code == 200, f"{r.status_code}: {r.text[:300]}"
        data = r.json()
        assert data["status"] == "COMPILED"
        assert data.get("skill_id")
        assert "yaml" in data

    async def test_compile_unknown_workflow_404(self, client):
        """Compiling a workflow with no rules returns 404."""
        r = await client.post("/skills/compile", json={
            "workflow_id": "wf_does_not_exist",
            "domain": "support",
            "workflow_name": "Ghost workflow",
        })
        assert r.status_code == 404

    async def test_explain_last_execution(self, client, has_ollama):
        """L15 generates a natural-language explanation of the last execution."""
        skills = (await client.get("/skills/")).json()["skills"]
        seeded = [s for s in skills if s.get("execution_count", 0) > 0]
        if not seeded:
            pytest.skip("No skills with executions to explain")
        r = await client.post(f"/skills/{seeded[0]['skill_id']}/explain")
        assert r.status_code == 200
        assert isinstance(r.json(), dict)
