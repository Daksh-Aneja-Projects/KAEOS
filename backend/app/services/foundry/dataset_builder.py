"""
KAEOS v2 — Enterprise AI Foundry, Phase 2: the Training Dataset Builder.

Turns governed enterprise activity into an explicit, exportable training set.

The v1 platform already stores every governed decision as a SkillExecution:
    task_intent      -> the instruction
    context          -> the grounding facts the agent reasoned over
    reasoning_chain  -> the reasoning that produced the answer
    status/outcome   -> whether it succeeded, and how
    hitl_approved    -> whether a human validated it

This service curates those rows into {instruction, context, ideal_answer,
reasoning, evaluation} tuples (TrainingExample), scored by how strong a training
signal each is. Because the source rows already walked the 7-gate pipeline, the
dataset inherits the platform's governance for free: a decision that was blocked
at the compliance gate, or that a human rejected, is never mined as a positive
example.

Two entry points:
    * mine_executions(...)  - batch-curate historical executions (idempotent).
    * record_human_feedback - capture a correction or rating the moment a human
                              gives it. This is the strongest signal there is and
                              the one thing SkillExecution does not already store:
                              the answer a human would have preferred.

Everything is tenant-scoped; the caller passes an already-tenant-bound session
(RLS enforces isolation at the row level regardless).
"""
import logging
from typing import Any, Dict, List, Optional

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import SkillExecution
from app.models.foundry import (
    TrainingExample,
    LABEL_CORRECTED,
    LABEL_APPROVED,
    LABEL_GOLD,
    LABEL_NEGATIVE,
    POSITIVE_LABELS,
)
from app.services.json_utils import plain_facts

logger = logging.getLogger(__name__)


# Outcome/status values that mean "a human edited the agent's answer" - the
# highest-value supervised signal, but we can only mine it once the corrected
# answer has been captured via record_human_feedback().
_EDITED_OUTCOMES = {"SUCCESS_WITH_EDIT", "HUMAN_OVERRIDDEN"}
_CLEAN_OK = {"SUCCESS_CLEAN"}


def _extract_answer(reasoning_chain: Any) -> Optional[str]:
    """Pull the accepted answer out of a reasoning chain, defensively.

    reasoning_chain is a list of step dicts; the final decision lives in the
    last step that carries a `decision` (falling back to output/result/
    tool_result). Shapes vary across agents, so never assume - degrade to the
    last step's string form rather than raising.
    """
    if not isinstance(reasoning_chain, list) or not reasoning_chain:
        return None
    for step in reversed(reasoning_chain):
        if not isinstance(step, dict):
            continue
        for key in ("decision", "output", "result", "answer", "tool_result"):
            val = step.get(key)
            if val:
                return val if isinstance(val, str) else _to_text(val)
    # Nothing structured - use the last step as-is.
    last = reasoning_chain[-1]
    return _to_text(last)


def _to_text(value: Any) -> str:
    import json
    try:
        return json.dumps(plain_facts(value) if isinstance(value, dict) else value, default=str)
    except Exception:
        return str(value)


def _classify(execution: SkillExecution) -> Optional[tuple[str, float]]:
    """Map an execution to (evaluation_label, quality_score), or None to skip.

    Quality is a training-signal weight in 0..1, not a business score:
      CORRECTED (human edited)  0.95 - what a human actually wanted
      APPROVED  (human OK'd)    0.90 - human-validated, unchanged
      GOLD      (clean success) 0.70 - trusted enough to run without a human
      NEGATIVE  (blocked/failed)0.40 - a contrastive example of what not to do
    """
    status = (execution.status or "").upper()
    outcome = (execution.outcome_type or "").upper()

    if execution.hitl_approved is True:
        return LABEL_APPROVED, 0.90
    if outcome in _EDITED_OUTCOMES or status in _EDITED_OUTCOMES:
        # The edited answer itself arrives via record_human_feedback(); mining
        # alone can only label it. We still emit the instruction+context so the
        # correction has somewhere to attach, but mark it CORRECTED.
        return LABEL_CORRECTED, 0.95
    if status in _CLEAN_OK and not execution.hitl_required:
        return LABEL_GOLD, 0.70
    if status.startswith("FAILED") or status.startswith("BLOCKED") or execution.hitl_approved is False:
        return LABEL_NEGATIVE, 0.40
    return None


async def mine_executions(
    db: AsyncSession,
    tenant_id: str,
    *,
    include_negative: bool = False,
    limit: int = 5000,
) -> Dict[str, Any]:
    """Curate this tenant's SkillExecutions into TrainingExamples.

    Idempotent: an execution already mined (source='mined') is skipped, so this
    is safe to run on every cadence. Returns a per-label summary.
    """
    # Already-mined execution ids - skip them so re-runs don't duplicate.
    seen_rows = await db.execute(
        select(TrainingExample.source_execution_id).where(
            TrainingExample.tenant_id == tenant_id,
            TrainingExample.source == "mined",
        )
    )
    seen = {r for (r,) in seen_rows if r}

    rows = await db.execute(
        select(SkillExecution)
        .where(SkillExecution.tenant_id == tenant_id)
        .order_by(SkillExecution.started_at.desc())
        .limit(limit)
    )
    executions = rows.scalars().all()

    created: Dict[str, int] = {}
    skipped = 0
    for ex in executions:
        if ex.id in seen:
            skipped += 1
            continue
        classified = _classify(ex)
        if classified is None:
            skipped += 1
            continue
        label, quality = classified
        if label == LABEL_NEGATIVE and not include_negative:
            skipped += 1
            continue

        example = TrainingExample(
            tenant_id=tenant_id,
            domain=_domain_of(ex),
            instruction=ex.task_intent or ex.skill_id_name or "(unspecified task)",
            context=plain_facts(ex.context) if isinstance(ex.context, dict) else {},
            ideal_answer=_extract_answer(ex.reasoning_chain) if label in POSITIVE_LABELS else None,
            reasoning=ex.reasoning_chain if isinstance(ex.reasoning_chain, list) else [],
            evaluation_label=label,
            quality_score=quality,
            human_verified=(label in (LABEL_APPROVED, LABEL_CORRECTED)),
            source="mined",
            source_execution_id=ex.id,
        )
        db.add(example)
        created[label] = created.get(label, 0) + 1

    await db.commit()
    total = sum(created.values())
    logger.info(f"[Foundry] Mined {total} training example(s) for {tenant_id} (skipped {skipped})")
    return {"tenant_id": tenant_id, "created": total, "by_label": created, "skipped": skipped}


async def record_human_feedback(
    db: AsyncSession,
    tenant_id: str,
    *,
    execution_id: Optional[str],
    corrected_answer: Optional[str] = None,
    rating: Optional[int] = None,
    instruction: Optional[str] = None,
    context: Optional[dict] = None,
) -> TrainingExample:
    """Capture the one signal SkillExecution does not already store: the answer
    a human would have preferred (a correction), or an explicit rating.

    A correction is the strongest example in the whole dataset - it is ground
    truth authored by the enterprise's own expert. If an execution_id is given
    we inherit its instruction/context so the correction is fully grounded.
    """
    inst = instruction
    ctx = context or {}
    ex: Optional[SkillExecution] = None
    if execution_id:
        res = await db.execute(
            select(SkillExecution).where(
                SkillExecution.id == execution_id,
                SkillExecution.tenant_id == tenant_id,
            )
        )
        ex = res.scalar_one_or_none()
        if ex is not None:
            inst = inst or ex.task_intent or ex.skill_id_name
            if not ctx and isinstance(ex.context, dict):
                ctx = plain_facts(ex.context)

    if corrected_answer:
        label, quality, source = LABEL_CORRECTED, 0.98, "human_correction"
    elif rating is not None:
        # A rating alone is a weak label: high rating reinforces the answer,
        # low rating marks it negative. Only positive ratings become answers.
        positive = rating >= 4
        label = LABEL_APPROVED if positive else LABEL_NEGATIVE
        quality = 0.85 if positive else 0.40
        source = "human_rating"
    else:
        raise ValueError("record_human_feedback needs either corrected_answer or rating")

    answer = corrected_answer
    if answer is None and ex is not None and label in POSITIVE_LABELS:
        answer = _extract_answer(ex.reasoning_chain)

    example = TrainingExample(
        tenant_id=tenant_id,
        domain=_domain_of(ex) if ex is not None else "general",
        instruction=inst or "(unspecified task)",
        context=ctx,
        ideal_answer=answer,
        reasoning=ex.reasoning_chain if (ex is not None and isinstance(ex.reasoning_chain, list)) else [],
        evaluation_label=label,
        quality_score=quality,
        human_verified=True,
        source=source,
        source_execution_id=execution_id,
    )
    db.add(example)
    await db.commit()
    await db.refresh(example)
    logger.info(f"[Foundry] Recorded {source} ({label}) for {tenant_id}")
    return example


async def dataset_stats(db: AsyncSession, tenant_id: str) -> Dict[str, Any]:
    """Summarise the tenant's training set: totals, and breakdown by label,
    domain, and source. This is the 'your data is now a training asset' view."""
    rows = await db.execute(
        select(
            TrainingExample.evaluation_label,
            TrainingExample.domain,
            TrainingExample.source,
            func.count(TrainingExample.id),
        )
        .where(TrainingExample.tenant_id == tenant_id)
        .group_by(TrainingExample.evaluation_label, TrainingExample.domain, TrainingExample.source)
    )
    by_label: Dict[str, int] = {}
    by_domain: Dict[str, int] = {}
    by_source: Dict[str, int] = {}
    total = 0
    for label, domain, source, count in rows:
        total += count
        by_label[label or "?"] = by_label.get(label or "?", 0) + count
        by_domain[domain or "general"] = by_domain.get(domain or "general", 0) + count
        by_source[source or "?"] = by_source.get(source or "?", 0) + count

    human = sum(v for k, v in by_source.items() if k in ("human_correction", "human_rating"))
    return {
        "tenant_id": tenant_id,
        "total_examples": total,
        "trainable_examples": sum(v for k, v in by_label.items() if k in POSITIVE_LABELS),
        "human_verified_examples": human,
        "by_label": by_label,
        "by_domain": by_domain,
        "by_source": by_source,
    }


async def export_examples(
    db: AsyncSession,
    tenant_id: str,
    *,
    domain: Optional[str] = None,
    min_quality: float = 0.0,
    positive_only: bool = True,
    limit: int = 10000,
) -> List[Dict[str, Any]]:
    """Emit the dataset as instruction-tuned JSON rows, ready for Phase 3
    fine-tuning. This is the concrete hand-off from Learning Intelligence to
    Model Evolution: each row is a supervised example.
    """
    conds = [TrainingExample.tenant_id == tenant_id, TrainingExample.quality_score >= min_quality]
    if domain:
        conds.append(TrainingExample.domain == domain)
    if positive_only:
        conds.append(TrainingExample.evaluation_label.in_(POSITIVE_LABELS))

    rows = await db.execute(
        select(TrainingExample)
        .where(*conds)
        .order_by(TrainingExample.quality_score.desc())
        .limit(limit)
    )
    out = []
    for e in rows.scalars().all():
        out.append({
            "instruction": e.instruction,
            "context": e.context or {},
            "output": e.ideal_answer or "",
            "reasoning": e.reasoning or [],
            "label": e.evaluation_label,
            "quality": e.quality_score,
            "domain": e.domain,
        })
    return out


def _domain_of(execution: Optional[SkillExecution]) -> str:
    """Best-effort domain from a skill name like 'finance.ap_dunning'."""
    if execution is None:
        return "general"
    name = execution.skill_id_name or ""
    if "." in name:
        return name.split(".", 1)[0]
    # context sometimes carries an explicit department
    if isinstance(execution.context, dict):
        dep = execution.context.get("department") or execution.context.get("domain")
        if dep:
            return str(dep)
    return "general"
