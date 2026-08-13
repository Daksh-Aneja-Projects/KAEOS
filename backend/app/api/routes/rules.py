"""KAEOS — Rules API Routes (L3 Polystore CRUD + L6 Confidence + L11 Provenance)"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func as sqlfunc
from typing import Optional
from datetime import datetime, timezone
import uuid

from app.core.database import get_db
from app.core.tenant import get_tenant_id, require_role
from app.models.domain import (
    Rule, ProvenanceLedger, ConfidenceHistory,
    ConfidenceTier,
)
from app.schemas.rules import (
    RuleCreate, RuleResponse, RuleValidateRequest,
    RuleListResponse,
)
from app.services.confidence import ConfidenceEngine

router = APIRouter(prefix="/rules", tags=["Rules — L3 Polystore"])
confidence_engine = ConfidenceEngine()


def _tier_from_scalar(s: float) -> ConfidenceTier:
    if s >= 0.95:
        return ConfidenceTier.VERIFIED
    if s >= 0.85:
        return ConfidenceTier.VALIDATED_DH
    if s >= 0.75:
        return ConfidenceTier.VALIDATED_MANAGER
    if s >= 0.60:
        return ConfidenceTier.VALIDATED_PEER
    if s >= 0.30:
        return ConfidenceTier.INFERRED
    return ConfidenceTier.SPECULATIVE


# Provenance entries go through the unified signed writer
# (app/services/provenance.py). The local sha256 helper this file used wrote a
# THIRD hash scheme into the shared chain_hash column, which is why the verify
# endpoint reported cleanly-created rules as TAMPERED.


@router.get("", response_model=RuleListResponse)
async def list_rules(
    domain: Optional[str] = None,
    confidence_tier: Optional[str] = None,
    is_executable: Optional[bool] = None,
    is_archived: bool = False,
    limit: int = Query(50, le=200),
    offset: int = 0,
    tenant_id: str = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """List rules with filtering by domain, confidence tier, execution status. Tenant-scoped to the caller."""
    q = select(Rule).where(Rule.tenant_id == tenant_id).where(Rule.is_archived == is_archived)
    if domain:
        q = q.where(Rule.domain == domain)
    if confidence_tier:
        q = q.where(Rule.confidence_tier == confidence_tier)
    if is_executable is not None:
        q = q.where(Rule.is_executable == is_executable)
    q = q.order_by(Rule.confidence_scalar.desc()).offset(offset).limit(limit)

    count_q = select(sqlfunc.count(Rule.id)).where(Rule.tenant_id == tenant_id).where(Rule.is_archived == is_archived)
    if domain:
        count_q = count_q.where(Rule.domain == domain)

    result = await db.execute(q)
    rules = result.scalars().all()
    total_result = await db.execute(count_q)
    total = total_result.scalar() or 0

    return RuleListResponse(
        total=total,
        rules=[RuleResponse.model_validate(r.__dict__) for r in rules],
    )


@router.get("/{rule_id}", response_model=RuleResponse)
async def get_rule(rule_id: str, tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    """Get a single rule with full confidence vector. Tenant-scoped to the caller."""
    result = await db.execute(
        select(Rule).where(Rule.tenant_id == tenant_id).where(Rule.id == rule_id)
    )
    rule = result.scalar_one_or_none()
    if not rule:
        raise HTTPException(404, "Rule not found")
    return RuleResponse.model_validate(rule.__dict__)


@router.post("", response_model=RuleResponse, status_code=201)
async def create_rule(body: RuleCreate, tenant: dict = Depends(require_role("operator")), db: AsyncSession = Depends(get_db)):
    """Create a new candidate rule (enters KB at INFERRED tier). Requires operator role.

    Maker-checker: a new rule ALWAYS lands non-executable, whatever its
    computed confidence. It starts steering governed decisions only after a
    different identity validates it (PUT /rules/{id}/validate). Confidence
    measures how well-evidenced a rule is, not whether a second pair of eyes
    has agreed the org should act on it - the old `scalar >= 0.60` shortcut
    conflated the two.
    """
    from app.core.tenant import approver_identity
    tenant_id = tenant["tenant_id"]
    maker = approver_identity(tenant)
    vector = {
        "source_breadth": 0.3,
        "source_authority": 0.4,
        "temporal_freshness": 1.0,
        "outcome_validation": 0.5,
        "explicit_validation": 0.0,
    }
    scalar = confidence_engine.calculate_scalar(vector)
    tier = _tier_from_scalar(scalar)

    rule = Rule(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        statement=body.statement,
        trigger_json=body.trigger_json,
        action_json=body.action_json,
        exceptions_json=body.exceptions_json,
        domain=body.domain,
        workflow_id=body.workflow_id,
        confidence_vector=vector,
        confidence_scalar=scalar,
        confidence_tier=tier,
        half_life_days=body.half_life_days,
        is_executable=False,  # maker-checker: executable only after validation
        authored_by=maker,
        compliance_tags=body.compliance_tags,
        access_level=body.access_level,
    )
    db.add(rule)

    # Provenance genesis entry via the unified signed writer (commits the
    # session, so the rule and its ledger entry land atomically).
    from app.services.provenance import append_ledger_event
    await append_ledger_event(
        db,
        tenant_id=tenant_id,
        rule_id=rule.id,
        event_type="CREATED",
        actor_hash="system",
        actor_role="extraction_engine",
        confidence_at=scalar,
        reasoning="New candidate rule ingested via API",
    )
    await db.refresh(rule)
    return RuleResponse.model_validate(rule.__dict__)


@router.put("/{rule_id}/validate", response_model=RuleResponse)
async def validate_rule(
    rule_id: str,
    body: RuleValidateRequest,
    tenant: dict = Depends(require_role("operator")),
    db: AsyncSession = Depends(get_db),
):
    """Bump a rule's confidence tier via human validation (L5 HITL gate). Tenant-scoped to the caller. Requires operator role.

    Maker-checker: validation is what makes a rule executable, so the checker
    is the AUTHENTICATED principal (client-supplied validator text is display
    metadata, not identity) and must differ from the rule's maker - the same
    person may not author a rule and then approve it into execution.
    """
    from app.core.tenant import approver_identity
    tenant_id = tenant["tenant_id"]
    checker = approver_identity(tenant)
    result = await db.execute(
        select(Rule).where(Rule.tenant_id == tenant_id).where(Rule.id == rule_id)
    )
    rule = result.scalar_one_or_none()
    if not rule:
        raise HTTPException(404, "Rule not found")
    if rule.authored_by and rule.authored_by == checker:
        raise HTTPException(
            403,
            "Four-eyes: the identity that authored this rule cannot also "
            "validate it. Ask a different operator to review it.",
        )

    old_scalar = rule.confidence_scalar
    vector = dict(rule.confidence_vector) if rule.confidence_vector else {}

    # Bayesian update for DEPT_HEAD_VALIDATION evidence
    new_scalar = confidence_engine.bayesian_update(old_scalar, "DEPT_HEAD_VALIDATION")
    vector["explicit_validation"] = 0.85 if body.new_tier == "VALIDATED_DH" else 0.95
    vector["temporal_freshness"] = 1.0  # just validated
    new_scalar = confidence_engine.calculate_scalar(vector)
    new_tier = _tier_from_scalar(new_scalar)

    rule.confidence_vector = vector
    rule.confidence_scalar = new_scalar
    rule.confidence_tier = new_tier
    # The checker's explicit approval IS the authorization to act - that is
    # what maker-checker means. Evidence confidence keeps its own job: the
    # runtime confidence gate still routes weak decisions to a human, so an
    # authorized-but-thinly-evidenced rule earns no free autonomy. (The old
    # `new_scalar >= 0.60` gate meant a human validation could fail to
    # authorize anything, while un-reviewed rules auto-armed at creation -
    # both directions of the same conflation.)
    rule.is_executable = True
    rule.validated_at = datetime.now(timezone.utc)
    # Non-repudiation: the recorded validator is the AUTHENTICATED principal.
    # body.validator_hash used to be recorded verbatim, letting any caller
    # attribute a validation to someone else.
    validated_by = list(rule.validated_by or [])
    validated_by.append(checker)
    rule.validated_by = validated_by

    # Log confidence history
    history = ConfidenceHistory(
        id=str(uuid.uuid4()),
        rule_id=rule.id,
        confidence_old=old_scalar,
        confidence_new=new_scalar,
        reason=f"VALIDATION_{body.new_tier.value}",
        changed_by=checker,
    )
    db.add(history)

    # Log provenance via the unified signed writer; it derives the chain head
    # itself (the manual newest-by-timestamp parent lookup here was one of the
    # ways concurrent validations forked the chain).
    from app.services.provenance import append_ledger_event
    await append_ledger_event(
        db,
        tenant_id=tenant_id,
        rule_id=rule.id,
        event_type="VALIDATED",
        actor_hash=checker,
        actor_role=body.validator_role,
        confidence_at=new_scalar,
        reasoning=f"Rule validated by {body.validator_role}. Tier: {new_tier.value}",
    )
    await db.refresh(rule)
    return RuleResponse.model_validate(rule.__dict__)


@router.get("/{rule_id}/provenance")
async def get_provenance(rule_id: str, tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    """Get the full provenance lineage chain for a rule (L11 Ledger).

    Tenant-scoped in the query, not left to RLS: this is the governance audit
    trail, and an endpoint that is only safe on Postgres is still wrong.
    """
    result = await db.execute(
        select(ProvenanceLedger)
        .where(
            ProvenanceLedger.rule_id == rule_id,
            ProvenanceLedger.tenant_id == tenant_id,
        )
        .order_by(ProvenanceLedger.timestamp.asc())
        .limit(500)   # append-only ledger, unbounded per rule
    )
    entries = result.scalars().all()
    if not entries:
        raise HTTPException(404, "No provenance found for this rule")
    return [
        {
            "id": e.id,
            "event_type": e.event_type,
            "timestamp": e.timestamp.isoformat() if e.timestamp else None,
            "actor_role": e.actor_role,
            "confidence_at": e.confidence_at,
            "reasoning": e.reasoning,
            "chain_hash": e.chain_hash,
        }
        for e in entries
    ]


@router.get("/{rule_id}/history")
async def get_confidence_history(rule_id: str, tenant_id: str = Depends(get_tenant_id), db: AsyncSession = Depends(get_db)):
    """Get confidence change history for a rule (L6 audit trail).

    `confidence_history` carries no tenant_id of its own, so the scope comes
    from its parent rule: a rule the caller's tenant does not own yields
    nothing rather than another tenant's confidence deltas.
    """
    owns = await db.execute(
        select(Rule.id).where(Rule.id == rule_id, Rule.tenant_id == tenant_id)
    )
    if owns.scalar_one_or_none() is None:
        raise HTTPException(404, "Rule not found")
    result = await db.execute(
        select(ConfidenceHistory)
        .where(ConfidenceHistory.rule_id == rule_id)
        .order_by(ConfidenceHistory.changed_at.desc())
        # Decay is scheduled, so this appends per rule on a timer with no human
        # involved. Newest-first, so the cap drops the oldest.
        .limit(500)
    )
    entries = result.scalars().all()
    return [
        {
            "id": e.id,
            "confidence_old": e.confidence_old,
            "confidence_new": e.confidence_new,
            "reason": e.reason,
            "changed_by": e.changed_by,
            "changed_at": e.changed_at.isoformat() if e.changed_at else None,
        }
        for e in entries
    ]
