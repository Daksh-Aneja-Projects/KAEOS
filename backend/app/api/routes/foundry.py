"""
KAEOS v2 — Enterprise AI Foundry API (Phase 2: Learning Intelligence).

Exposes the training-dataset layer built on top of the platform's governed
execution history:

    POST /foundry/feedback         capture a human correction or rating
    POST /foundry/datasets/build   curate historical executions into examples
    GET  /foundry/datasets         summarise the tenant's training set
    GET  /foundry/datasets/export  emit instruction-tuned rows for fine-tuning

Every route is tenant-scoped by the JWT-derived tenant (get_tenant_id) and
backstopped by RLS. Nothing here mutates existing execution/provenance data -
this layer is purely additive: it reads governed history and writes a curated
dataset alongside it.
"""
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.tenant import get_tenant_id, require_role
from app.core.database import get_db
from app.services.foundry import dataset_builder

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/foundry", tags=["AI Foundry"])


@router.post("/feedback")
async def record_feedback(
    body: dict,
    tenant: dict = Depends(require_role("operator")),
    db: AsyncSession = Depends(get_db),
):
    """Record a human correction or rating against an agent decision.

    Body: { execution_id?, corrected_answer?, rating?, instruction?, context? }
    A corrected_answer is the strongest training signal there is - expert ground
    truth. A rating (1-5) is a lighter signal. One of the two is required.

    Requires operator role — this writes a curated training example, the same
    tier as its sibling POST /foundry/datasets/build.
    """
    tenant_id = tenant["tenant_id"]
    try:
        example = await dataset_builder.record_human_feedback(
            db,
            tenant_id,
            execution_id=body.get("execution_id"),
            corrected_answer=body.get("corrected_answer"),
            rating=body.get("rating"),
            instruction=body.get("instruction"),
            context=body.get("context"),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {
        "id": example.id,
        "evaluation_label": example.evaluation_label,
        "quality_score": example.quality_score,
        "source": example.source,
    }


@router.post("/datasets/build")
async def build_dataset(
    body: dict | None = None,
    tenant: dict = Depends(require_role("operator")),
    db: AsyncSession = Depends(get_db),
):
    """Curate this tenant's governed executions into training examples.

    Idempotent - already-mined executions are skipped, so this is safe to call
    on a schedule. Body (optional): { include_negative?: bool, limit?: int }.
    Requires operator role.
    """
    tenant_id = tenant["tenant_id"]
    body = body or {}
    result = await dataset_builder.mine_executions(
        db,
        tenant_id,
        include_negative=bool(body.get("include_negative", False)),
        limit=int(body.get("limit", 5000)),
    )
    return result


@router.get("/datasets")
async def get_dataset_stats(
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """Summarise the training set: totals and breakdown by label/domain/source.
    This is the 'your enterprise activity is now a training asset' view."""
    return await dataset_builder.dataset_stats(db, tenant_id)


@router.get("/datasets/export")
async def export_dataset(
    domain: str | None = None,
    min_quality: float = 0.0,
    positive_only: bool = True,
    limit: int = 10000,
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """Emit instruction-tuned rows ready for Phase 3 fine-tuning."""
    examples = await dataset_builder.export_examples(
        db,
        tenant_id,
        domain=domain,
        min_quality=min_quality,
        positive_only=positive_only,
        limit=limit,
    )
    return {"tenant_id": tenant_id, "count": len(examples), "examples": examples}


# ── Phase 3: Model Evolution (evaluate a candidate, gated promotion) ──────────

def _run_out(run) -> dict:
    return {
        "id": run.id,
        "tier": run.tier,
        "baseline_model": run.baseline_model,
        "candidate_model": run.candidate_model,
        "status": run.status,
        "eval_size": run.eval_size,
        "baseline_score": run.baseline_score,
        "candidate_score": run.candidate_score,
        "score_delta": run.score_delta,
        "win": run.win,
        "simulated": run.simulated,
        "decision": run.decision,
        "decided_by": run.decided_by,
        "detail": run.detail,
        "error": run.error,
    }


class EvolutionEvalRequest(BaseModel):
    tier: str                                  # reasoning | classification | fast
    candidate_model: str
    baseline_model: str | None = None
    eval_limit: int = 20


@router.post("/evolution/evaluate")
async def evaluate_candidate_model(
    body: EvolutionEvalRequest,
    tenant: dict = Depends(require_role("operator")),
    db: AsyncSession = Depends(get_db),
):
    """Measure a candidate model against the tenant's baseline on held-out
    governed examples. Real generations, deterministic scoring. Requires operator.

    A win is recorded but NEVER auto-applied — promotion is a separate, admin-gated
    step. An evaluation with no live provider is flagged ``simulated`` and cannot win.
    """
    from app.services.foundry import model_evolution
    try:
        run = await model_evolution.run_evaluation(
            db, tenant["tenant_id"], tier=body.tier,
            candidate_model=body.candidate_model, baseline_model=body.baseline_model,
            eval_limit=body.eval_limit,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return _run_out(run)


@router.get("/evolution/runs")
async def list_evolution_runs(
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    from app.services.foundry import model_evolution
    runs = await model_evolution.list_runs(db, tenant_id)
    return {"runs": [_run_out(r) for r in runs]}


@router.get("/evolution/runs/{run_id}")
async def get_evolution_run(
    run_id: str,
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    from app.services.foundry import model_evolution
    run = await model_evolution._get_run(db, tenant_id, run_id)
    if run is None:
        raise HTTPException(404, "evolution run not found")
    return _run_out(run)


@router.post("/evolution/runs/{run_id}/promote")
async def promote_evolution_run(
    run_id: str,
    tenant: dict = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """Promote a winning candidate to the tenant's model for its tier (gated deploy).

    Admin-only and audit-logged. Refuses simulated or non-winning runs. Writes the
    tenant's BYOK routing and forces a re-probe so the gates re-derive the ceiling.
    """
    from app.services.foundry import model_evolution
    from app.core.audit import record_security_event
    try:
        run = await model_evolution.promote(
            db, tenant["tenant_id"], run_id, approver=tenant.get("name") or "admin",
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    await record_security_event(
        tenant_id=tenant["tenant_id"], event_type="CONFIG_CHANGE", action="WRITE",
        actor=tenant.get("name"), actor_role=tenant.get("role"),
        resource_type="model_promotion", resource_id=run.candidate_model,
        details={"tier": run.tier, "delta": run.score_delta},
    )
    return _run_out(run)


@router.post("/evolution/runs/{run_id}/reject")
async def reject_evolution_run(
    run_id: str,
    tenant: dict = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    from app.services.foundry import model_evolution
    try:
        run = await model_evolution.reject(
            db, tenant["tenant_id"], run_id, approver=tenant.get("name") or "admin",
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return _run_out(run)
