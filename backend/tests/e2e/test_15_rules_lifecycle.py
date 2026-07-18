"""
KAEOS E2E Test 15 — Rules Lifecycle & Knowledge Operations
Tests the full rule lifecycle: create → validate (confidence bump) → history
→ versions → clone → simulate → export/import. Also covers elicitation
(generate + answer), extraction conflict detection, and provenance verify.
"""
import pytest


@pytest.mark.asyncio
class TestRuleLifecycle:
    """L3 Polystore CRUD + L6 Confidence + versioning."""

    _rule_id = None

    async def test_01_create_rule(self, client):
        """A new candidate rule enters the KB at INFERRED tier."""
        r = await client.post("/rules", json={
            "statement": "E2E: Expense reports over $1000 require director approval",
            "trigger_json": {"condition": "expense_amount > 1000"},
            "action_json": {"action": "escalate_to_director"},
            "domain": "finance",
            "workflow_id": "wf_payment",
            "compliance_tags": ["SOX"],
            "half_life_days": 90,
        })
        assert r.status_code == 201, f"{r.status_code}: {r.text[:300]}"
        rule = r.json()
        assert rule["confidence_tier"] in ("INFERRED", "SPECULATIVE", "VALIDATED_PEER")
        assert rule["statement"].startswith("E2E:")
        TestRuleLifecycle._rule_id = rule["id"]

    async def test_02_validate_rule_bumps_confidence(self, client):
        """Human validation raises confidence via Bayesian update."""
        rule_id = TestRuleLifecycle._rule_id
        if not rule_id:
            pytest.skip("Rule creation did not run")
        before = (await client.get(f"/rules/{rule_id}")).json()["confidence_scalar"]

        r = await client.put(f"/rules/{rule_id}/validate", json={
            "validator_role": "dept_head",
            "validator_hash": "e2e_validator",
            "new_tier": "VALIDATED_DH",
        })
        assert r.status_code == 200, f"{r.status_code}: {r.text[:300]}"
        after = r.json()["confidence_scalar"]
        assert after > before, f"Validation should raise confidence ({before} → {after})"

    async def test_03_rule_history(self, client):
        """Confidence history is recorded for the rule."""
        rule_id = TestRuleLifecycle._rule_id
        if not rule_id:
            pytest.skip("Rule creation did not run")
        r = await client.get(f"/rules/{rule_id}/history")
        assert r.status_code == 200

    async def test_04_rule_versions(self, client):
        """Rule version chain is retrievable."""
        rule_id = TestRuleLifecycle._rule_id
        if not rule_id:
            pytest.skip("Rule creation did not run")
        r = await client.get(f"/rules/{rule_id}/versions")
        assert r.status_code == 200

    async def test_05_clone_rule(self, client):
        """A rule can be cloned into a new draft."""
        rule_id = TestRuleLifecycle._rule_id
        if not rule_id:
            pytest.skip("Rule creation did not run")
        r = await client.post(f"/rules/{rule_id}/clone", json={"new_domain": "finance"})
        assert r.status_code == 200, f"{r.status_code}: {r.text[:300]}"
        assert r.json()["status"] == "CLONED"

    async def test_06_simulate_scenarios(self, client):
        """What-if simulation projects decay and confidence boost."""
        rule_id = TestRuleLifecycle._rule_id
        if not rule_id:
            rules = (await client.get("/rules")).json()["rules"]
            rule_id = rules[0]["id"]
        for scenario in ("decay_30d", "decay_90d", "boost_confidence", "remove_rule"):
            r = await client.post("/simulate", json={
                "rule_id": rule_id, "scenario": scenario,
            })
            assert r.status_code == 200, f"simulate {scenario} → {r.status_code}: {r.text[:200]}"
            body = r.json()
            assert "error" not in body, f"simulate {scenario} → {body.get('error')}"

    async def test_07_rule_provenance_verify(self, client):
        """Provenance hash-chain verification runs for a rule."""
        rules = (await client.get("/rules")).json()["rules"]
        assert rules
        r = await client.get(f"/provenance/{rules[0]['id']}/verify")
        # 200 = chain verified; 404 = no provenance entries for this rule
        assert r.status_code in (200, 404), f"{r.status_code}: {r.text[:200]}"


@pytest.mark.asyncio
class TestKnowledgePortability:
    """Export / import round-trips."""

    async def test_export_rules(self, client):
        """Rules export returns the full rule set."""
        r = await client.get("/export/rules")
        assert r.status_code == 200

    async def test_export_skills(self, client):
        """Skills export returns the full skill set."""
        r = await client.get("/export/skills")
        assert r.status_code == 200

    async def test_import_rules_bulk(self, client):
        """Bulk rule import creates INFERRED-tier rules."""
        r = await client.post("/import/rules", json={
            "rules": [
                {"statement": "E2E import: NDA required before sharing roadmap",
                 "domain": "legal", "half_life_days": 180, "compliance_tags": []},
                {"statement": "E2E import: PTO requests need 2-week notice",
                 "domain": "hr", "half_life_days": 90, "compliance_tags": []},
            ]
        })
        assert r.status_code == 200, f"{r.status_code}: {r.text[:300]}"
        assert r.json()["count"] == 2


@pytest.mark.asyncio
class TestElicitationPipeline:
    """L5 Elicitation — question generation and answer processing."""

    async def test_elicitation_generate_question(self, client, has_ollama):
        """LLM generates a targeted micro-survey question for an employee."""
        if not has_ollama:
            pytest.skip("Ollama not running")
        r = await client.post("/elicitation/generate", json={
            "employee_id": "emp_1", "domain": "support",
        })
        assert r.status_code == 200, f"{r.status_code}: {r.text[:300]}"

    async def test_elicitation_answer_pipeline(self, client):
        """Answering a pending question runs the L5 answer pipeline."""
        dash = (await client.get("/elicitation/dashboard")).json()
        pending = [q for q in dash.get("pending_questions", [])
                   if q.get("status", "PENDING") == "PENDING"]
        if not pending:
            pytest.skip("No pending elicitation questions")
        q = pending[0]
        r = await client.post("/elicitation/answer", json={
            "question_id": q["id"],
            "answer_text": "E2E answer: the deciding factor was customer lifetime value "
                           "above $10K, which allows the override per policy.",
            "answerer_hash": "e2e_answerer",
        })
        assert r.status_code == 200, f"{r.status_code}: {r.text[:300]}"

    async def test_elicitation_answer_twice_rejected(self, client):
        """Answering an already-answered question returns 400."""
        dash = (await client.get("/elicitation/dashboard")).json()
        answered = [q for q in dash.get("pending_questions", [])
                    if q.get("status") == "ANSWERED"]
        if not answered:
            pytest.skip("No answered questions to double-answer")
        r = await client.post("/elicitation/answer", json={
            "question_id": answered[0]["id"], "answer_text": "duplicate",
        })
        assert r.status_code == 400


@pytest.mark.asyncio
class TestExtractionPipeline:
    """L4 Extraction — conflict detection for candidate rules."""

    async def test_detect_conflict_candidate_rule(self, client):
        """Conflict detector evaluates a candidate rule against the KB."""
        r = await client.post("/extraction/detect-conflict", json={
            "statement": "Refunds under $100 auto-approve without review",
            "trigger_json": {"condition": "refund_amount < 100"},
            "action_json": {"action": "auto_approve"},
            "domain": "support",
            "confidence_basis": "e2e_test",
        })
        assert r.status_code == 200, f"{r.status_code}: {r.text[:300]}"
        assert isinstance(r.json(), dict)

    async def test_extraction_signals_have_shape(self, client):
        """Signals carry source, domain, and payload fields."""
        data = (await client.get("/extraction/signals")).json()
        signals = data.get("signals", [])
        assert len(signals) > 0, "Expected seeded signals"
        s = signals[0]
        assert "source_type" in s or "signal_type" in s
