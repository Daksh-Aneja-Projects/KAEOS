"""L2 closed loop — the external fine-tune bridge.

Model evolution (``model_evolution.py``) already MEASURES a candidate model and
gates its promotion. What was missing is the step that PRODUCES the candidate:
submit the tenant's curated positive examples to an external fine-tuning
provider, poll to completion, and on success auto-trigger a real
``ModelEvolutionRun``. Promotion stays human-gated.

Providers are pluggable behind ``FineTuneProvider``:
  * ``OpenAIFineTuneProvider`` — real OpenAI fine-tuning (needs an API key).
  * ``NullFineTuneProvider``   — no provider configured; a submit fails HONESTLY
                                 ("no fine-tune provider configured") rather than
                                 fabricating a model. Nothing here ever invents a
                                 candidate the evaluator would then trust.

Tests inject a fake provider to exercise the submit -> poll -> auto-eval loop
without a live account.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.foundry import FineTuneJob

logger = logging.getLogger(__name__)

_MIN_EXAMPLES = 10          # too-small a set makes fine-tuning meaningless
_ACTIVE = ("SUBMITTED", "RUNNING")


class FineTuneError(Exception):
    """A recoverable fine-tune bridge failure (recorded on the job, never raised to a gate)."""


# ── provider abstraction ──────────────────────────────────────────────────────

class FineTuneProvider(ABC):
    name = "abstract"

    @abstractmethod
    async def submit(self, *, base_model: str, examples: list[dict]) -> str:
        """Upload the dataset + start a fine-tune. Returns the provider job id."""

    @abstractmethod
    async def poll(self, external_job_id: str) -> dict:
        """Return {"status": SUBMITTED|RUNNING|SUCCEEDED|FAILED, "model": <id?>, "error": <str?>}."""


class NullFineTuneProvider(FineTuneProvider):
    """No provider configured — fail honestly rather than fake a model."""
    name = "none"

    async def submit(self, *, base_model, examples):
        raise FineTuneError(
            "no fine-tune provider configured (set OPENAI_API_KEY, or inject a provider)")

    async def poll(self, external_job_id):
        return {"status": "FAILED", "error": "no fine-tune provider configured"}


class OpenAIFineTuneProvider(FineTuneProvider):
    """Real OpenAI fine-tuning via the REST API (JSONL upload + fine_tuning.jobs)."""
    name = "openai"

    def __init__(self, api_key: str):
        self._key = api_key

    def _to_jsonl(self, examples: list[dict]) -> bytes:
        import json
        lines = []
        for ex in examples:
            msgs = [
                {"role": "system", "content": "You are a governed enterprise agent."},
                {"role": "user", "content": _render_prompt(ex)},
                {"role": "assistant", "content": ex.get("output", "")},
            ]
            lines.append(json.dumps({"messages": msgs}))
        return ("\n".join(lines)).encode("utf-8")

    async def submit(self, *, base_model, examples) -> str:
        import httpx
        headers = {"Authorization": f"Bearer {self._key}"}
        async with httpx.AsyncClient(timeout=60.0) as client:
            files = {"file": ("kaeos_ft.jsonl", self._to_jsonl(examples), "application/jsonl")}
            up = await client.post("https://api.openai.com/v1/files", headers=headers,
                                   data={"purpose": "fine-tune"}, files=files)
            if up.status_code >= 300:
                raise FineTuneError(f"file upload failed ({up.status_code}): {up.text[:200]}")
            file_id = up.json().get("id")
            job = await client.post(
                "https://api.openai.com/v1/fine_tuning/jobs", headers=headers,
                json={"training_file": file_id, "model": base_model or "gpt-4o-mini-2024-07-18"})
            if job.status_code >= 300:
                raise FineTuneError(f"job create failed ({job.status_code}): {job.text[:200]}")
            return job.json()["id"]

    async def poll(self, external_job_id: str) -> dict:
        import httpx
        headers = {"Authorization": f"Bearer {self._key}"}
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.get(
                f"https://api.openai.com/v1/fine_tuning/jobs/{external_job_id}", headers=headers)
        if r.status_code >= 300:
            return {"status": "RUNNING"}   # transient; keep polling rather than fail the job
        body = r.json()
        st = body.get("status")            # validating_files|queued|running|succeeded|failed|cancelled
        if st == "succeeded":
            return {"status": "SUCCEEDED", "model": body.get("fine_tuned_model")}
        if st in ("failed", "cancelled"):
            return {"status": "FAILED", "error": str(body.get("error") or st)}
        return {"status": "RUNNING"}


def _render_prompt(ex: dict) -> str:
    import json
    ctx = ex.get("context")
    ctx_str = json.dumps(ctx, default=str) if ctx else ""
    return f"{ex.get('instruction', '')}\n\nContext:\n{ctx_str}".strip()


def get_finetune_provider() -> FineTuneProvider:
    """Resolve the configured provider (OpenAI when a key is set, else Null)."""
    from app.core.config import get_settings
    key = getattr(get_settings(), "OPENAI_API_KEY", "") or ""
    return OpenAIFineTuneProvider(key) if key else NullFineTuneProvider()


# ── the bridge ────────────────────────────────────────────────────────────────

async def submit_finetune(db: AsyncSession, tenant_id: str, *, tier: str,
                          base_model: Optional[str] = None,
                          provider: Optional[FineTuneProvider] = None) -> FineTuneJob:
    """Export the tenant's positive examples and submit a fine-tune job."""
    from app.services.foundry import dataset_builder
    from app.services.llm_router import LLMRouter

    prov = provider or get_finetune_provider()
    base = base_model or LLMRouter.MODEL_TIERS.get(tier) or "gpt-4o-mini-2024-07-18"

    examples = await dataset_builder.export_examples(
        db, tenant_id, min_quality=0.6, positive_only=True, limit=5000)

    job = FineTuneJob(tenant_id=tenant_id, tier=tier, provider=prov.name,
                      base_model=base, example_count=len(examples), status="SUBMITTED")
    if len(examples) < _MIN_EXAMPLES:
        job.status = "FAILED"
        job.error = f"not enough training examples ({len(examples)} < {_MIN_EXAMPLES})"
        db.add(job)
        await db.commit()
        await db.refresh(job)
        return job

    try:
        job.external_job_id = await prov.submit(base_model=base, examples=examples)
        job.status = "RUNNING"
    except FineTuneError as e:
        job.status = "FAILED"
        job.error = str(e)[:1000]
    db.add(job)
    await db.commit()
    await db.refresh(job)
    return job


async def poll_finetune_jobs(db: AsyncSession, tenant_id: Optional[str] = None,
                             provider: Optional[FineTuneProvider] = None) -> dict:
    """Poll active jobs; on success auto-trigger a real evaluation (human-gated promote)."""
    from app.services.foundry import model_evolution

    q = select(FineTuneJob).where(FineTuneJob.status.in_(_ACTIVE))
    if tenant_id:
        q = q.where(FineTuneJob.tenant_id == tenant_id)
    jobs = (await db.execute(q)).scalars().all()

    advanced = 0
    for job in jobs:
        prov = provider or get_finetune_provider()
        if not job.external_job_id:
            job.status = "FAILED"
            job.error = "missing external job id"
            advanced += 1
            continue
        try:
            res = await prov.poll(job.external_job_id)
        except Exception as e:  # never let a poll error kill the sweep
            logger.warning("[finetune] poll error for %s: %s", job.id, e)
            continue

        status = res.get("status")
        if status == "RUNNING" or status == "SUBMITTED":
            continue
        if status == "FAILED":
            job.status = "FAILED"
            job.error = str(res.get("error") or "provider reported failure")[:1000]
            advanced += 1
            continue
        if status == "SUCCEEDED":
            job.result_model = res.get("model")
            if not job.result_model:
                job.status = "FAILED"
                job.error = "provider reported success but no model id"
                advanced += 1
                continue
            job.status = "EVALUATING"
            # Auto-trigger a REAL evaluation of the fine-tuned candidate vs baseline.
            try:
                run = await model_evolution.run_evaluation(
                    db, job.tenant_id, tier=job.tier, candidate_model=job.result_model)
                job.eval_run_id = run.id
                job.status = "EVALUATED"
            except Exception as e:
                job.status = "FAILED"
                job.error = f"auto-eval failed: {e}"[:1000]
            advanced += 1

    if advanced:
        await db.commit()
    return {"polled": len(jobs), "advanced": advanced}
