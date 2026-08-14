"""Regulatory & Risk Autopilot (v3 Phase 6).

Compliance is a *gate* elsewhere in KAEOS; this is the continuous regulatory
*intelligence* on top of it, computed from real data:
  - regulation -> control mapping (which skills carry which framework tags),
  - an EU-AI-Act-style per-skill risk register (tier from autonomy + tags +
    high-consequence surface),
  - a continuous monitor of recent compliance events (blocks / audit fails /
    human overrides), and
  - audit-ready evidence packs assembled from the provenance + actions ledgers.
Nothing is invented: every number traces to a Skill, an execution, or a ledger row.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import Skill, SkillExecution

logger = logging.getLogger(__name__)

# Frameworks KAEOS reasons about, with a one-line scope for the UI.
FRAMEWORKS = {
    "SOX": "Financial reporting & controls",
    "GDPR": "EU personal-data protection",
    "HIPAA": "US health information privacy",
    "CCPA": "California consumer privacy",
    "EEOC": "US employment non-discrimination",
    "PCI": "Payment card data security",
    "EU_AI_ACT": "EU AI system risk governance",
    "SEC": "Securities disclosure",
    "SOC2": "Service org security & availability",
    "ISO27001": "Information security management",
}

# High-consequence surface (money movement, terminations, contract execution, deletes).
_HIGH_CONSEQUENCE_TOKENS = (
    "payment", "payout", "wire", "invoice_pay", "refund", "terminat", "offboard",
    "contract", "delete", "purge", "deploy", "release",
)


def classify_risk(skill: Skill) -> dict:
    """EU-AI-Act-style risk classification for one deployed skill.

    HIGH   — regulated AND high-consequence (or very low confidence): needs the
             strongest oversight.
    LIMITED — regulated OR high-consequence: transparency + human oversight.
    MINIMAL — neither.
    Autonomy is the confidence the skill can clear (higher = more autonomous).
    """
    tags = [t.upper() for t in (skill.compliance_tags or [])]
    blob = f"{skill.skill_id or ''} {skill.department or ''}".lower()
    regulated = bool(tags)
    high_consequence = any(tok in blob for tok in _HIGH_CONSEQUENCE_TOKENS)
    conf = skill.confidence or 0.0

    if (regulated and high_consequence) or (regulated and conf < 0.7):
        tier = "HIGH"
    elif regulated or high_consequence:
        tier = "LIMITED"
    else:
        tier = "MINIMAL"

    # Obligations implied by the tier (what governance the tier requires).
    obligations = {
        "HIGH": ["human_oversight", "logging", "risk_assessment", "transparency"],
        "LIMITED": ["logging", "transparency"],
        "MINIMAL": ["logging"],
    }[tier]

    return {
        "skill_id": skill.skill_id,
        "department": skill.department or skill.domain,
        "frameworks": tags,
        "autonomy": round(conf, 3),
        "high_consequence": high_consequence,
        "risk_tier": tier,
        "obligations": obligations,
    }


async def build_overview(db: AsyncSession, tenant_id: str, days: int = 30) -> dict:
    """The autopilot overview: control map, risk register, and the live monitor."""
    skills = (await db.execute(
        select(Skill).where(Skill.tenant_id == tenant_id, Skill.status == "ACTIVE")
    )).scalars().all()

    register = [classify_risk(s) for s in skills]
    tier_counts = {"HIGH": 0, "LIMITED": 0, "MINIMAL": 0}
    for r in register:
        tier_counts[r["risk_tier"]] += 1

    # Regulation -> control mapping: framework -> the skills that carry it.
    control_map: dict[str, list[str]] = {}
    for r in register:
        for fw in r["frameworks"]:
            control_map.setdefault(fw, []).append(r["skill_id"])

    # Continuous monitor: recent compliance-relevant execution outcomes.
    since = datetime.now(timezone.utc) - timedelta(days=days)
    monitor_states = ("BLOCKED_COMPLIANCE", "FAILED_AUDIT", "HUMAN_OVERRIDDEN")
    rows = (await db.execute(
        select(SkillExecution.status, func.count())
        .where(SkillExecution.tenant_id == tenant_id,
               SkillExecution.started_at >= since)
        .group_by(SkillExecution.status)
    )).all()
    monitor = {s: int(c) for s, c in rows if s in monitor_states}

    return {
        "window_days": days,
        # Only surface frameworks we can actually assemble an evidence pack for -
        # skills also carry non-regulatory tags (e.g. SLA, I9) that would 404 the
        # evidence route if rendered as clickable buttons.
        "frameworks": [
            {"framework": fw, "scope": FRAMEWORKS[fw], "controls": len(skills_)}
            for fw, skills_ in sorted(control_map.items()) if fw in FRAMEWORKS
        ],
        "risk_register": sorted(register, key=lambda r: {"HIGH": 0, "LIMITED": 1, "MINIMAL": 2}[r["risk_tier"]]),
        "risk_summary": tier_counts,
        "control_map": control_map,
        "monitor": {
            "compliance_blocks": monitor.get("BLOCKED_COMPLIANCE", 0),
            "audit_failures": monitor.get("FAILED_AUDIT", 0),
            "human_overrides": monitor.get("HUMAN_OVERRIDDEN", 0),
        },
        "note": "Risk tiers, control coverage, and the monitor are computed from real skills and executions.",
    }


# An evidence pack carries a bounded, recent SAMPLE of the underlying rows (not
# just counts) so an auditor can spot-verify the hash chain and the actions -
# capped so a large tenant does not return a megabyte of ledger.
_EVIDENCE_SAMPLE_CAP = 20
# People frameworks whose primary evidence is the disparate-impact audit trail.
_PEOPLE_FRAMEWORKS = {"EEOC", "GDPR"}


def _clip(text, n: int = 240) -> str | None:
    """Truncate free-text so a pack never leaks a full reasoning blob (PII risk)."""
    if not text:
        return None
    s = str(text)
    return s if len(s) <= n else s[:n] + "..."


def _iso(dt):
    return dt.isoformat() if dt is not None else None


async def evidence_pack(db: AsyncSession, tenant_id: str, framework: str, days: int = 90) -> dict:
    """Assemble an audit-ready evidence pack for a framework from real ledgers.

    Every section reports ``{count, sample, sample_size}``: the count for scale,
    the sample (most-recent rows, capped) so the claim is spot-verifiable rather
    than an unfalsifiable assertion. All queries stay tenant-scoped (RLS).
    """
    framework = framework.upper()
    since = datetime.now(timezone.utc) - timedelta(days=days)

    skills = (await db.execute(
        select(Skill).where(Skill.tenant_id == tenant_id, Skill.status == "ACTIVE")
    )).scalars().all()
    covered = [s.skill_id for s in skills if framework in [t.upper() for t in (s.compliance_tags or [])]]

    evidence: dict = {"framework": framework, "scope": FRAMEWORKS.get(framework, ""),
                      "window_days": days, "controls": covered, "control_count": len(covered)}
    evidence_rows = 0  # any real sampled row makes the pack falsifiable -> complete

    # Provenance ledger entries (hash-chained decisions) in-window + a sample so
    # the chain_hash is inspectable.
    prov_count = 0
    prov_sample: list[dict] = []
    try:
        from app.models.domain import ProvenanceLedger
        prov_count = int((await db.execute(
            select(func.count()).select_from(ProvenanceLedger)
            .where(ProvenanceLedger.tenant_id == tenant_id, ProvenanceLedger.timestamp >= since)
        )).scalar() or 0)
        prov_rows = (await db.execute(
            select(ProvenanceLedger)
            .where(ProvenanceLedger.tenant_id == tenant_id, ProvenanceLedger.timestamp >= since)
            .order_by(ProvenanceLedger.timestamp.desc()).limit(_EVIDENCE_SAMPLE_CAP)
        )).scalars().all()
        prov_sample = [{
            "id": r.id, "timestamp": _iso(r.timestamp), "event_type": r.event_type,
            "rule_id": r.rule_id, "actor_role": r.actor_role,
            "chain_hash": r.chain_hash, "reasoning": _clip(r.reasoning),
        } for r in prov_rows]
    except Exception:
        logger.warning("provenance evidence failed for tenant %s", tenant_id, exc_info=True)
    evidence["provenance_entries"] = prov_count
    evidence["provenance_sample"] = prov_sample
    evidence["provenance_sample_size"] = len(prov_sample)
    evidence_rows += len(prov_sample)

    # Actions ledger (what KAEOS actually did) in-window + a sample.
    act_count = 0
    act_sample: list[dict] = []
    try:
        from app.models.actuation import ActionRecord
        act_count = int((await db.execute(
            select(func.count()).select_from(ActionRecord)
            .where(ActionRecord.tenant_id == tenant_id, ActionRecord.created_at >= since)
        )).scalar() or 0)
        act_rows = (await db.execute(
            select(ActionRecord)
            .where(ActionRecord.tenant_id == tenant_id, ActionRecord.created_at >= since)
            .order_by(ActionRecord.created_at.desc()).limit(_EVIDENCE_SAMPLE_CAP)
        )).scalars().all()
        act_sample = [{
            "id": r.id, "created_at": _iso(r.created_at), "system": r.system,
            "operation": r.operation, "status": r.status,
            "reversed_at": _iso(r.reversed_at), "actor": r.actor,
        } for r in act_rows]
    except Exception:
        logger.warning("actuation evidence failed for tenant %s", tenant_id, exc_info=True)
    evidence["actions_recorded"] = act_count
    evidence["actions_sample"] = act_sample
    evidence["actions_sample_size"] = len(act_sample)
    evidence_rows += len(act_sample)

    # Executions of the covered controls in-window (the audit trail) + a sample.
    exec_count = 0
    exec_sample: list[dict] = []
    if covered:
        exec_count = int((await db.execute(
            select(func.count()).select_from(SkillExecution)
            .where(SkillExecution.tenant_id == tenant_id,
                   SkillExecution.skill_id_name.in_(covered),
                   SkillExecution.started_at >= since)
        )).scalar() or 0)
        exec_rows = (await db.execute(
            select(SkillExecution)
            .where(SkillExecution.tenant_id == tenant_id,
                   SkillExecution.skill_id_name.in_(covered),
                   SkillExecution.started_at >= since)
            .order_by(SkillExecution.started_at.desc()).limit(_EVIDENCE_SAMPLE_CAP)
        )).scalars().all()
        exec_sample = [{
            "id": r.id, "skill_id_name": r.skill_id_name, "status": r.status,
            "started_at": _iso(r.started_at), "hitl_required": r.hitl_required,
            "hitl_approved": r.hitl_approved, "hitl_approver": r.hitl_approver,
        } for r in exec_rows]
    evidence["control_executions"] = exec_count
    evidence["control_executions_sample"] = exec_sample
    evidence["control_executions_sample_size"] = len(exec_sample)
    evidence_rows += len(exec_sample)

    # People frameworks: the disparate-impact audit trail is the core evidence.
    if framework in _PEOPLE_FRAMEWORKS:
        fair_count = 0
        fair_sample: list[dict] = []
        try:
            from app.models.fairness import FairnessAuditLog
            fair_count = int((await db.execute(
                select(func.count()).select_from(FairnessAuditLog)
                .where(FairnessAuditLog.tenant_id == tenant_id,
                       FairnessAuditLog.created_at >= since)
            )).scalar() or 0)
            fair_rows = (await db.execute(
                select(FairnessAuditLog)
                .where(FairnessAuditLog.tenant_id == tenant_id,
                       FairnessAuditLog.created_at >= since)
                .order_by(FairnessAuditLog.created_at.desc()).limit(_EVIDENCE_SAMPLE_CAP)
            )).scalars().all()
            fair_sample = [{
                "id": r.id, "fairness_score": r.fairness_score, "passed": r.passed,
                "flagged_attributes": r.flagged_attributes, "method": _clip(r.rationale, 120),
                "was_overridden": r.was_overridden, "override_by": r.override_by,
                "created_at": _iso(r.created_at),
            } for r in fair_rows]
        except Exception:
            logger.warning("fairness evidence failed for tenant %s", tenant_id, exc_info=True)
        evidence["fairness_assessments"] = fair_count
        evidence["fairness_sample"] = fair_sample
        evidence["fairness_sample_size"] = len(fair_sample)
        evidence_rows += len(fair_sample)

    evidence["generated_at"] = None  # stamped by the caller / route
    # An "evidence pack" with covered controls but zero underlying rows is an
    # assertion, not evidence: complete requires both.
    evidence["complete"] = len(covered) > 0 and evidence_rows > 0
    return evidence
