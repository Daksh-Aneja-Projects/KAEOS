"""L2 closed loop — the external fine-tune bridge.

A fake provider exercises submit -> poll -> auto-evaluate without a live account.
Nothing here promotes: promotion stays human-gated (the existing /promote route).
"""
import uuid

import pytest

from app.services.foundry.finetune import (
    FineTuneProvider, NullFineTuneProvider, submit_finetune, poll_finetune_jobs,
)
from app.models.foundry import TrainingExample, ModelEvolutionRun, FineTuneJob

pytestmark = pytest.mark.asyncio

T = "tenant_ft"


class _FakeProvider(FineTuneProvider):
    name = "fake"

    def __init__(self, model="ft:fake:v1"):
        self.model = model
        self.submitted = False

    async def submit(self, *, base_model, examples):
        self.submitted = True
        assert examples, "provider should receive the exported examples"
        return "ftjob-123"

    async def poll(self, external_job_id):
        return {"status": "SUCCEEDED", "model": self.model}


async def _seed_examples(db, tenant, n=12):
    for i in range(n):
        db.add(TrainingExample(
            id=str(uuid.uuid4()), tenant_id=tenant, domain="operations",
            instruction=f"do task {i}", context={"k": i}, ideal_answer=f"answer {i}",
            reasoning=[{"decision": f"answer {i}"}], evaluation_label="APPROVED",
            quality_score=0.8, human_verified=True, source="mined",
        ))
    await db.commit()


async def test_submit_then_poll_auto_evaluates(db):
    await _seed_examples(db, T, 12)
    prov = _FakeProvider()

    job = await submit_finetune(db, T, tier="reasoning", provider=prov)
    assert job.status == "RUNNING"
    assert job.external_job_id == "ftjob-123"
    assert prov.submitted is True

    res = await poll_finetune_jobs(db, tenant_id=T, provider=prov)
    assert res["advanced"] == 1

    from sqlalchemy import select
    refreshed = (await db.execute(select(FineTuneJob).where(FineTuneJob.id == job.id))).scalar_one()
    assert refreshed.status == "EVALUATED"
    assert refreshed.result_model == "ft:fake:v1"
    assert refreshed.eval_run_id is not None

    # A REAL evaluation run was created for the fine-tuned candidate (human-gated to promote).
    run = (await db.execute(
        select(ModelEvolutionRun).where(ModelEvolutionRun.id == refreshed.eval_run_id))).scalar_one()
    assert run.candidate_model == "ft:fake:v1"
    assert run.decision is None   # NOT auto-promoted


async def test_no_provider_fails_honestly(db):
    await _seed_examples(db, T, 12)
    job = await submit_finetune(db, T, tier="fast", provider=NullFineTuneProvider())
    assert job.status == "FAILED"
    assert "no fine-tune provider configured" in (job.error or "")


async def test_thin_dataset_is_rejected(db):
    await _seed_examples(db, "tenant_thin", 3)   # below the minimum
    job = await submit_finetune(db, "tenant_thin", tier="fast", provider=_FakeProvider())
    assert job.status == "FAILED"
    assert "not enough training examples" in (job.error or "")
