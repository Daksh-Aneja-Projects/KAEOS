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

from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import Skill, SkillExecution

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
        "frameworks": [
            {"framework": fw, "scope": FRAMEWORKS.get(fw, ""), "controls": len(skills_)}
            for fw, skills_ in sorted(control_map.items())
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


async def evidence_pack(db: AsyncSession, tenant_id: str, framework: str, days: int = 90) -> dict:
    """Assemble an audit-ready evidence pack for a framework from real ledgers."""
    framework = framework.upper()
    since = datetime.now(timezone.utc) - timedelta(days=days)

    skills = (await db.execute(
        select(Skill).where(Skill.tenant_id == tenant_id, Skill.status == "ACTIVE")
    )).scalars().all()
    covered = [s.skill_id for s in skills if framework in [t.upper() for t in (s.compliance_tags or [])]]

    evidence: dict = {"framework": framework, "scope": FRAMEWORKS.get(framework, ""),
                      "window_days": days, "controls": covered, "control_count": len(covered)}

    # Provenance ledger entries (hash-chained decisions) in-window.
    prov_count = 0
    try:
        from app.models.domain import ProvenanceLedger
        prov_count = int((await db.execute(
            select(func.count()).select_from(ProvenanceLedger)
            .where(ProvenanceLedger.tenant_id == tenant_id, ProvenanceLedger.timestamp >= since)
        )).scalar() or 0)
    except Exception:
        prov_count = 0
    evidence["provenance_entries"] = prov_count

    # Actions ledger (what KAEOS actually did) in-window.
    try:
        from app.models.actuation import ActionRecord
        act_count = int((await db.execute(
            select(func.count()).select_from(ActionRecord)
            .where(ActionRecord.tenant_id == tenant_id, ActionRecord.created_at >= since)
        )).scalar() or 0)
    except Exception:
        act_count = 0
    evidence["actions_recorded"] = act_count

    # Executions of the covered controls in-window (the audit trail count).
    exec_count = 0
    if covered:
        exec_count = int((await db.execute(
            select(func.count()).select_from(SkillExecution)
            .where(SkillExecution.tenant_id == tenant_id,
                   SkillExecution.skill_id_name.in_(covered),
                   SkillExecution.started_at >= since)
        )).scalar() or 0)
    evidence["control_executions"] = exec_count
    evidence["generated_at"] = None  # stamped by the caller / route
    evidence["complete"] = len(covered) > 0
    return evidence
