"""
KAEOS E2E Test 29 — AI Foundry, Phase 2: Learning Intelligence.

The platform already logs every governed decision as a SkillExecution. Phase 2
curates that history into an explicit, exportable training dataset, and captures
the one signal executions don't already store: the answer a human would have
preferred (a correction).

These tests pin the contract so the layer can't silently regress:
  * building a dataset is idempotent (safe to run on a schedule)
  * a human correction is the highest-quality example and is tenant-scoped
  * feedback with neither a correction nor a rating is a 400, not a silent no-op
  * export emits instruction-tuned rows ready for fine-tuning
"""
import pytest


@pytest.mark.asyncio
class TestDatasetBuild:
    async def test_build_returns_summary(self, client):
        r = await client.post("/foundry/datasets/build", json={})
        assert r.status_code == 200, f"{r.status_code}: {r.text[:200]}"
        data = r.json()
        for key in ("tenant_id", "created", "by_label", "skipped"):
            assert key in data, f"missing '{key}' in {list(data)}"
        assert isinstance(data["created"], int)

    async def test_build_is_idempotent(self, client):
        """A second build must not re-mine executions already curated."""
        (await client.post("/foundry/datasets/build", json={})).json()  # first build mines everything
        second = (await client.post("/foundry/datasets/build", json={})).json()
        # Everything mined the first time is skipped the second time.
        assert second["created"] == 0, (
            f"re-run created {second['created']} duplicate example(s); "
            "mining is not idempotent"
        )


@pytest.mark.asyncio
class TestHumanFeedback:
    async def test_correction_is_highest_quality(self, client):
        r = await client.post("/foundry/feedback", json={
            "instruction": "Draft a dunning email for invoice INV-TEST-29",
            "context": {"invoice": "INV-TEST-29", "days_late": 45},
            "corrected_answer": "Polite firm reminder citing net-30 terms and a 2% late fee.",
        })
        assert r.status_code == 200, f"{r.status_code}: {r.text[:200]}"
        data = r.json()
        assert data["evaluation_label"] == "CORRECTED"
        assert data["quality_score"] >= 0.9
        assert data["source"] == "human_correction"

    async def test_rating_is_recorded(self, client):
        r = await client.post("/foundry/feedback", json={
            "instruction": "Rate this triage",
            "rating": 5,
        })
        assert r.status_code == 200, f"{r.status_code}: {r.text[:200]}"
        assert r.json()["evaluation_label"] == "APPROVED"

    async def test_low_rating_is_negative(self, client):
        r = await client.post("/foundry/feedback", json={
            "instruction": "Rate this triage",
            "rating": 1,
        })
        assert r.status_code == 200
        assert r.json()["evaluation_label"] == "NEGATIVE"

    async def test_empty_feedback_is_rejected(self, client):
        r = await client.post("/foundry/feedback", json={"instruction": "nothing"})
        assert r.status_code == 400, (
            f"feedback with no correction or rating should 400, got {r.status_code}"
        )


@pytest.mark.asyncio
class TestDatasetStatsAndExport:
    async def test_stats_reflect_recorded_feedback(self, client):
        # Ensure at least one trainable example exists.
        await client.post("/foundry/feedback", json={
            "instruction": "Summarise contract risk for MSA-29",
            "corrected_answer": "Cap on liability is uncapped in section 9 - flag it.",
        })
        r = await client.get("/foundry/datasets")
        assert r.status_code == 200, f"{r.status_code}: {r.text[:200]}"
        data = r.json()
        for key in ("total_examples", "trainable_examples",
                    "human_verified_examples", "by_label", "by_domain", "by_source"):
            assert key in data, f"missing '{key}' in {list(data)}"
        assert data["total_examples"] >= 1
        assert data["human_verified_examples"] >= 1
        assert data["trainable_examples"] >= 1

    async def test_export_emits_instruction_tuned_rows(self, client):
        await client.post("/foundry/feedback", json={
            "instruction": "Export-shape probe for test 29",
            "corrected_answer": "This is the accepted answer.",
        })
        r = await client.get("/foundry/datasets/export", params={"positive_only": True})
        assert r.status_code == 200, f"{r.status_code}: {r.text[:200]}"
        data = r.json()
        assert data["count"] >= 1
        row = data["examples"][0]
        for key in ("instruction", "context", "output", "reasoning", "label", "quality", "domain"):
            assert key in row, f"export row missing '{key}': {list(row)}"
