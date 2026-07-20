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
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.tenant import get_tenant_id, require_role
from app.core.database import get_db
from app.services.foundry import dataset_builder

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/foundry", tags=["AI Foundry"])


@router.post("/feedback")
async def record_feedback(
    body: dict,
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """Record a human correction or rating against an agent decision.

    Body: { execution_id?, corrected_answer?, rating?, instruction?, context? }
    A corrected_answer is the strongest training signal there is - expert ground
    truth. A rating (1-5) is a lighter signal. One of the two is required.
    """
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
