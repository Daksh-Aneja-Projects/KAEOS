"""KAEOS v2 — Enterprise AI Foundry, Phase 3: Model Evolution (real).

The honest core of "model evolution": take a CANDIDATE model (a stronger model,
or one fine-tuned externally on this tenant's Phase-2 export) and MEASURE it
against the tenant's current BASELINE model on a held-out slice of the tenant's
own governed training examples. Real generations, real scores, a real decision.

Guarantees, so nothing here is theatre:
  * Scoring is deterministic (token-F1 + exact match) — no LLM-judges-itself.
  * The eval set is a stable, hashed held-out slice, reproducible across runs.
  * If evaluation ran without a live LLM provider (simulated responses), the run
    is flagged ``simulated`` and can NEVER win or be promoted — a fabricated
    score must not drive a model swap.
  * Promotion is GATED: a candidate only becomes the tenant's model for a tier
    when it beats the baseline by a margin AND a human (admin) approves. It then
    writes the tenant's BYOK routing (TenantLLMConfig) and the model registry.

What this module deliberately does NOT do: train weights. The training step is
external/pluggable (submit the Phase-2 JSONL to a fine-tune provider, bring the
resulting model id back as the candidate). Shipping a fake trainer would violate
the platform's core honesty, so it is absent by design.
"""
from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.foundry import ModelEvolutionRun
from app.services.foundry import dataset_builder

logger = logging.getLogger(__name__)

WIN_MARGIN = 0.02          # candidate must beat baseline by at least this much
MIN_EVAL_EXAMPLES = 5      # below this, a comparison is too noisy to trust
_TIER_TO_LAYER = {
    "reasoning": "TIER_1_COMPLEX",
    "classification": "TIER_2_STANDARD",
    "fast": "TIER_3_FAST",
}


# ── Deterministic scoring (no LLM) ───────────────────────────────────────────

def _normalize(text: str) -> list[str]:
    return re.sub(r"[^\w\s]", " ", (text or "").lower()).split()


def score_text(prediction: str, reference: str) -> float:
    """Similarity in [0,1]: 1.0 for an exact normalized match, else token-F1.

    Token-F1 is the standard span-answer metric (SQuAD): it rewards getting the
    right content words without demanding a character-perfect match, which is the
    right shape for governed decision text.
    """
    pred, ref = _normalize(prediction), _normalize(reference)
    if not pred and not ref:
        return 1.0
    if not pred or not ref:
        return 0.0
    if pred == ref:
        return 1.0
    from collections import Counter
    common = Counter(pred) & Counter(ref)
    overlap = sum(common.values())
    if overlap == 0:
        return 0.0
    precision = overlap / len(pred)
    recall = overlap / len(ref)
    return 2 * precision * recall / (precision + recall)


def _build_prompt(example: dict) -> str:
    ctx = example.get("context") or {}
    ctx_str = ""
    if isinstance(ctx, dict) and ctx:
        ctx_str = "\nContext:\n" + "\n".join(f"- {k}: {v}" for k, v in list(ctx.items())[:20])
    return (
        f"Task: {example.get('instruction', '')}{ctx_str}\n\n"
        "Answer concisely with the decision only."
    )


def _held_out(examples: list[dict], limit: int) -> list[dict]:
    """Deterministic, reproducible slice: sort by a content hash, take ``limit``.

    Hash-ordering means the same corpus always yields the same eval set, so two
    runs of the same candidate are comparable, and it does not privilege recent
    or high-quality rows in a way that would bias the comparison."""
    keyed = sorted(
        examples,
        key=lambda e: hashlib.sha256(
            f"{e.get('instruction','')}|{e.get('output','')}".encode()
        ).hexdigest(),
    )
    return keyed[:limit]


# ── Evaluation ───────────────────────────────────────────────────────────────

async def _resolve_baseline(db: AsyncSession, tenant_id: str, tier: str) -> str:
    """This tenant's current model for the tier (BYOK), else the platform default."""
    from app.models.settings import TenantLLMConfig
    from app.services.llm_router import LLMRouter

    layer = _TIER_TO_LAYER.get(tier)
    if layer:
        row = (await db.execute(
            select(TenantLLMConfig).where(
                TenantLLMConfig.tenant_id == tenant_id,
                TenantLLMConfig.layer == layer,
            )
        )).scalar_one_or_none()
        if row:
            return row.model_name
    return LLMRouter.MODEL_TIERS.get(tier, "ollama/qwen2.5-coder:7b")


async def run_evaluation(
    db: AsyncSession,
    tenant_id: str,
    *,
    tier: str,
    candidate_model: str,
    baseline_model: Optional[str] = None,
    eval_limit: int = 20,
    router=None,
) -> ModelEvolutionRun:
    """Evaluate ``candidate_model`` vs the baseline on held-out governed examples.

    Persists and returns a ModelEvolutionRun. ``router`` is injectable for tests;
    in production a tenant-bound BYOK router is built. Never raises for an empty
    dataset or a missing provider — it records a FAILED / simulated run instead.
    """
    if tier not in _TIER_TO_LAYER:
        raise ValueError(f"tier must be one of {sorted(_TIER_TO_LAYER)}")

    baseline_model = baseline_model or await _resolve_baseline(db, tenant_id, tier)
    run = ModelEvolutionRun(
        tenant_id=tenant_id, tier=tier,
        baseline_model=baseline_model, candidate_model=candidate_model,
        status="EVALUATING",
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)

    # Held-out eval corpus: positive, reasonably-high-quality examples that carry
    # a reference answer.
    examples = await dataset_builder.export_examples(
        db, tenant_id, positive_only=True, min_quality=0.6, limit=5000,
    )
    examples = [e for e in examples if (e.get("output") or "").strip()]
    eval_set = _held_out(examples, eval_limit)

    if len(eval_set) < MIN_EVAL_EXAMPLES:
        run.status = "FAILED"
        run.eval_size = len(eval_set)
        run.error = (
            f"insufficient held-out examples ({len(eval_set)} < {MIN_EVAL_EXAMPLES}). "
            "Build the Phase-2 dataset first (POST /foundry/datasets/build)."
        )
        await db.commit()
        await db.refresh(run)
        return run

    if router is None:
        from app.services.llm_router import LLMRouter
        router = await LLMRouter.for_tenant(tenant_id)

    async def _generate(model: str, prompt: str) -> tuple[str, bool]:
        res = await router.complete(prompt=prompt, model=model, temperature=0.0, max_tokens=256)
        if isinstance(res, str):
            return res, False
        return (res.get("content") or ""), bool(res.get("simulated"))

    base_total = cand_total = 0.0
    simulated = False
    per_example = []
    for ex in eval_set:
        prompt = _build_prompt(ex)
        ref = ex["output"]
        base_out, b_sim = await _generate(baseline_model, prompt)
        cand_out, c_sim = await _generate(candidate_model, prompt)
        simulated = simulated or b_sim or c_sim
        b_score = score_text(base_out, ref)
        c_score = score_text(cand_out, ref)
        base_total += b_score
        cand_total += c_score
        per_example.append({
            "instruction": ex.get("instruction", "")[:120],
            "baseline_score": round(b_score, 4),
            "candidate_score": round(c_score, 4),
        })

    n = len(eval_set)
    base_mean = base_total / n
    cand_mean = cand_total / n
    delta = cand_mean - base_mean
    win = (delta >= WIN_MARGIN) and not simulated

    run.eval_size = n
    run.baseline_score = round(base_mean, 4)
    run.candidate_score = round(cand_mean, 4)
    run.score_delta = round(delta, 4)
    run.simulated = simulated
    run.win = win
    run.detail = {
        "margin": WIN_MARGIN,
        "metric": "exact_match|token_f1",
        "notes": (
            "Evaluation ran without a live LLM provider — scores are simulated and "
            "cannot justify promotion." if simulated else
            "Real generations scored against held-out governed reference answers."
        ),
        "per_example": per_example[:50],
    }
    # A win still requires a human to approve promotion — never auto-promote.
    run.status = "PENDING_REVIEW" if win else "EVALUATED"
    await db.commit()
    await db.refresh(run)
    logger.info(
        "[Foundry][Evolution] tenant=%s tier=%s candidate=%s base=%.3f cand=%.3f win=%s sim=%s",
        tenant_id, tier, candidate_model, base_mean, cand_mean, win, simulated,
    )
    return run


# ── Gated promotion / rejection ──────────────────────────────────────────────

async def promote(db: AsyncSession, tenant_id: str, run_id: str, approver: str) -> ModelEvolutionRun:
    """Make the candidate the tenant's model for its tier (gated deploy).

    Guards: the run must have genuinely won a non-simulated evaluation and not
    already be decided. Writes the tenant's BYOK routing (TenantLLMConfig) so the
    router immediately uses it, invalidates the stale capability profile (forcing
    a re-probe → the gates re-derive the ceiling for the new model), and records
    it in the model registry.
    """
    run = await _get_run(db, tenant_id, run_id)
    if run is None:
        raise ValueError("evolution run not found")
    if run.decision:
        raise ValueError(f"run already decided: {run.decision}")
    if run.simulated:
        raise ValueError("cannot promote a simulated evaluation (no real provider ran)")
    if not run.win or run.status not in ("EVALUATED", "PENDING_REVIEW"):
        raise ValueError("only a candidate that won its evaluation can be promoted")

    from app.models.settings import TenantLLMConfig
    from app.services.llm_router import LLMRouter

    layer = _TIER_TO_LAYER[run.tier]
    provider = LLMRouter._get_provider(run.candidate_model)

    cfg = (await db.execute(
        select(TenantLLMConfig).where(
            TenantLLMConfig.tenant_id == tenant_id,
            TenantLLMConfig.layer == layer,
        )
    )).scalar_one_or_none()
    if not cfg:
        cfg = TenantLLMConfig(tenant_id=tenant_id, layer=layer)
        db.add(cfg)
    cfg.model_name = run.candidate_model
    cfg.provider = provider
    cfg.capability_profile = {}   # a new model must be re-probed before it earns a ceiling

    await _register_model(db, tenant_id, run.candidate_model, provider, run.tier)

    run.decision = "PROMOTED"
    run.status = "PROMOTED"
    run.decided_by = approver
    run.decided_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(run)
    logger.info("[Foundry][Evolution] PROMOTED %s → tenant=%s tier=%s by %s",
                run.candidate_model, tenant_id, run.tier, approver)
    return run


async def reject(db: AsyncSession, tenant_id: str, run_id: str, approver: str) -> ModelEvolutionRun:
    run = await _get_run(db, tenant_id, run_id)
    if run is None:
        raise ValueError("evolution run not found")
    if run.decision:
        raise ValueError(f"run already decided: {run.decision}")
    run.decision = "REJECTED"
    run.status = "REJECTED"
    run.decided_by = approver
    run.decided_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(run)
    return run


async def list_runs(db: AsyncSession, tenant_id: str, limit: int = 50) -> list[ModelEvolutionRun]:
    rows = await db.execute(
        select(ModelEvolutionRun)
        .where(ModelEvolutionRun.tenant_id == tenant_id)
        .order_by(ModelEvolutionRun.created_at.desc())
        .limit(limit)
    )
    return list(rows.scalars().all())


async def _get_run(db: AsyncSession, tenant_id: str, run_id: str) -> Optional[ModelEvolutionRun]:
    return (await db.execute(
        select(ModelEvolutionRun).where(
            ModelEvolutionRun.id == run_id,
            ModelEvolutionRun.tenant_id == tenant_id,
        )
    )).scalar_one_or_none()


async def _register_model(db: AsyncSession, tenant_id: str, model_name: str, provider: str, tier: str) -> None:
    """Best-effort model-registry entry for the promoted model (non-fatal)."""
    try:
        from app.models.infrastructure import ModelRegistryEntry, ModelTier
        tier_enum = {
            "reasoning": ModelTier.DEEP,
            "classification": ModelTier.STANDARD,
            "fast": ModelTier.FAST,
        }.get(tier, ModelTier.STANDARD)
        existing = (await db.execute(
            select(ModelRegistryEntry).where(
                ModelRegistryEntry.tenant_id == tenant_id,
                ModelRegistryEntry.model_name == model_name,
            )
        )).scalar_one_or_none()
        if existing is None:
            db.add(ModelRegistryEntry(
                tenant_id=tenant_id, model_name=model_name, provider=provider,
                tier=tier_enum, is_active=True,
            ))
    except Exception as e:  # registry is a convenience mirror, not the source of truth
        logger.warning("[Foundry][Evolution] model registry write skipped: %s", e)
