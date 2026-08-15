"""KAEOS HR Vertical — Requisition fairness sweep.

Turns real recruiting outcomes into the aggregated cohort counts the statistical
four-fifths disparate-impact test needs, then runs them through the ONE gated
executor so an adverse-impact finding routes to the real HITL queue (not a
parallel fairness path). This is what makes the statistical test fire in prod:
per-candidate screening always runs n=1 and never supplies cohort_outcomes.
"""
from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.hr.models.recruiting import Candidate, CandidateStage
from app.services.disparate_impact import SMALL_SAMPLE_N

logger = logging.getLogger(__name__)

# A candidate has reached a selection decision once they hit one of these stages
# (or the AI scored them). Selection = decided AND not rejected/withdrawn.
_DECIDED_STAGES = {
    CandidateStage.HIRED, CandidateStage.OFFER_EXTENDED, CandidateStage.OFFER_PREP,
    CandidateStage.REJECTED, CandidateStage.WITHDRAWN,
}
_NOT_SELECTED = {CandidateStage.REJECTED, CandidateStage.WITHDRAWN}
# Protected attributes read from voluntary self-ID (Candidate.eeoc_data).
_DEFAULT_ATTRS = ("gender", "ethnicity", "age_band")


def _stage(c: Candidate) -> CandidateStage:
    return c.stage if isinstance(c.stage, CandidateStage) else CandidateStage(c.stage)


async def build_cohort_outcomes(
    db: AsyncSession, tenant_id: str, requisition_id: Optional[str],
    attributes: Optional[tuple] = None,
) -> dict:
    """Aggregate decided candidates into {attr: {group: {selected, total}}}.

    Protected attributes come only from ``Candidate.eeoc_data`` (voluntary
    self-ID); a candidate with no eeoc_data is skipped (never guessed). Returns
    ``{"cohorts": {...}, "decided_total": int}``. ``requisition_id=None``
    aggregates every requisition tenant-wide — used by the org-wide EEOC
    compliance-report generator, not just the per-requisition sweep.
    """
    attrs = tuple(attributes or _DEFAULT_ATTRS)
    stmt = select(Candidate).where(Candidate.tenant_id == tenant_id)
    if requisition_id is not None:
        stmt = stmt.where(Candidate.requisition_id == requisition_id)
    rows = (await db.execute(stmt)).scalars().all()

    cohorts: dict = {}
    decided_total = 0
    for c in rows:
        stage = _stage(c)
        if stage not in _DECIDED_STAGES and c.ai_score is None:
            continue
        eeoc = c.eeoc_data if isinstance(c.eeoc_data, dict) else None
        if not eeoc:
            continue
        decided_total += 1
        selected = 0 if stage in _NOT_SELECTED else 1
        for attr in attrs:
            group = eeoc.get(attr)
            if not group:
                continue
            bucket = cohorts.setdefault(attr, {}).setdefault(
                str(group), {"selected": 0, "total": 0})
            bucket["total"] += 1
            bucket["selected"] += selected

    return {"cohorts": cohorts, "decided_total": decided_total}


async def run_requisition_fairness_sweep(
    db: AsyncSession, tenant_id: str, requisition_id: str,
) -> dict:
    """Run the statistical disparate-impact audit for one requisition.

    Below the sample floor (or with no attribute carrying two groups) the result
    is advisory INSUFFICIENT_GROUPS and never hard-blocks on noise. At/above the
    floor the cohort flows through the gated executor: the fairness gate runs the
    four-fifths test and routes any adverse impact to HITL (PENDING_HITL).
    """
    built = await build_cohort_outcomes(db, tenant_id, requisition_id)
    cohorts = built["cohorts"]
    total = built["decided_total"]
    usable = any(len(groups) >= 2 for groups in cohorts.values())
    if total < SMALL_SAMPLE_N or not usable:
        return {
            "status": "INSUFFICIENT_GROUPS",
            "requisition_id": requisition_id,
            "decided_total": total,
            "cohorts": cohorts,
        }

    from app.hr.agents.gated_runner import run_gated_hr_skill

    result = await run_gated_hr_skill(
        skill_id="hr_requisition_fairness_sweep",
        steps=[{
            "id": "audit", "action": "audit selection rates for disparate impact",
            "tool": "none", "condition": "Always", "thresholds": "None",
        }],
        context={
            "cohort_outcomes": cohorts,
            "affected_entity_type": "Candidate",
            "affected_count": total,
            "intent": f"disparate-impact audit for requisition {requisition_id}",
        },
        tenant_id=tenant_id,
        # No compliance tags on purpose: the fairness gate IS the EEOC
        # adverse-impact test here. Tagging EEOC compliance too would run the
        # same four-fifths test in the compliance gate and pre-empt with a
        # terminal BLOCKED_COMPLIANCE instead of a reviewable HITL pause.
        compliance_tags=[],
        requires_fairness=True,
    )
    result.setdefault("requisition_id", requisition_id)
    result["decided_total"] = total
    return result
