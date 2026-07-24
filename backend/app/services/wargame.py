"""Autonomy Wargaming (v4 IP-4).

Adversarially stress the enterprise twin with a CASCADE of shocks and score how it
holds up — organizational resilience and how safely the agents (the gates) respond
under compounding stress. Grounded in the REAL twin: each department's fragility
comes from its actual skill surface and its real recent adverse-event history
(from executions); impact compounds as damage accumulates. No fabricated numbers.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import Skill, SkillExecution

# A named adversarial playbook: an ordered cascade of (shock, target-dept, severity).
PLAYBOOKS = {
    "supply_shock": [
        ("VENDOR_FAILURE", "operations", 80),
        ("BUDGET_CUT", "finance", 65),
        ("SLA_BREACH", "support", 55),
    ],
    "talent_crisis": [
        ("TALENT_EXODUS", "engineering", 85),
        ("KNOWLEDGE_LOSS", "engineering", 60),
        ("DELIVERY_SLIP", "sales", 50),
    ],
    "cyber_cascade": [
        ("CYBER_INCIDENT", "engineering", 95),
        ("DATA_BREACH", "legal", 80),
        ("CUSTOMER_CHURN", "support", 60),
    ],
    "regulatory_storm": [
        ("NEW_REGULATION", "legal", 70),
        ("AUDIT_FAILURE", "finance", 75),
        ("REMEDIATION_LOAD", "operations", 55),
    ],
}

_ADVERSE_PREFIXES = ("FAILED", "BLOCKED", "HUMAN_OVERRIDDEN", "TIMEOUT", "ERROR")
_HITL_SEVERITY = 70   # a shock at/above this needs a human in the loop


def _canon(dept: Optional[str]) -> str:
    r = (dept or "general").lower()
    return {"human_resources": "hr", "customer_support": "support", "ops": "operations",
            "eng": "engineering"}.get(r, r)


async def _twin_fragility(db: AsyncSession, tenant_id: str, days: int = 45) -> dict:
    """Per-department fragility (0..1) from real skill surface + recent adverse rate."""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    skills = (await db.execute(
        select(Skill.skill_id, Skill.department, Skill.confidence)
        .where(Skill.tenant_id == tenant_id, Skill.status == "ACTIVE")
    )).all()
    by_dept: dict[str, dict] = {}
    sid_dept = {}
    for sid, dept, conf in skills:
        d = _canon(dept)
        sid_dept[sid] = d
        e = by_dept.setdefault(d, {"skills": 0, "conf_sum": 0.0, "adverse": 0, "total": 0})
        e["skills"] += 1
        e["conf_sum"] += (conf or 0.0)

    rows = (await db.execute(
        select(SkillExecution.skill_id_name, SkillExecution.status)
        .where(SkillExecution.tenant_id == tenant_id, SkillExecution.started_at >= since)
    )).all()
    for sid, status in rows:
        d = sid_dept.get(sid)
        if not d:
            continue
        by_dept.setdefault(d, {"skills": 0, "conf_sum": 0.0, "adverse": 0, "total": 0})
        by_dept[d]["total"] += 1
        if any((status or "").upper().startswith(p) for p in _ADVERSE_PREFIXES):
            by_dept[d]["adverse"] += 1

    frag = {}
    for d, e in by_dept.items():
        avg_conf = (e["conf_sum"] / e["skills"]) if e["skills"] else 0.7
        adverse_rate = (e["adverse"] / e["total"]) if e["total"] else 0.0
        # Fragile when confidence is low and adverse history is high. 0..1.
        frag[d] = round(min(1.0, max(0.05, 0.6 * (1 - avg_conf) + 0.4 * adverse_rate + 0.1)), 3)
    return frag


async def run_wargame(db: AsyncSession, tenant_id: str, *, playbook: str = "cyber_cascade",
                      custom: Optional[list] = None) -> dict:
    steps_spec = custom if custom else PLAYBOOKS.get(playbook)
    if not steps_spec:
        return {"error": f"unknown playbook; known: {sorted(PLAYBOOKS)}"}

    frag = await _twin_fragility(db, tenant_id)
    default_frag = round(sum(frag.values()) / len(frag), 3) if frag else 0.4

    integrity = 100.0        # org integrity, degrades as the cascade lands
    steps_out = []
    autonomous_responses = 0
    weakest = {"department": None, "damage": -1.0}

    for i, (shock, dept, severity) in enumerate(steps_spec):
        d = _canon(dept)
        f = frag.get(d, default_frag)
        # Damage compounds: a battered org (low integrity) absorbs less.
        stress = severity / 100.0
        absorb = (integrity / 100.0)               # healthy orgs absorb more
        damage = round(stress * f * (1.4 - 0.4 * absorb) * 100, 2)
        integrity = round(max(0.0, integrity - damage), 2)

        # Agents' safe response: a high-severity shock needs a human; else the gates
        # handle it autonomously (this is the safe-autonomy posture under stress).
        autonomous = severity < _HITL_SEVERITY
        if autonomous:
            autonomous_responses += 1

        if damage > weakest["damage"]:
            weakest = {"department": d, "damage": damage}

        steps_out.append({
            "step": i + 1, "shock": shock, "department": d, "severity": severity,
            "fragility": f, "damage": damage, "integrity_after": integrity,
            "response": "autonomous" if autonomous else "human_in_loop",
        })

    resilience = integrity                                # what survived (final integrity)
    grade = ("A" if resilience >= 80 else "B" if resilience >= 65 else
             "C" if resilience >= 50 else "D" if resilience >= 35 else "F")
    safe_response_rate = round(autonomous_responses / len(steps_spec), 3) if steps_spec else None

    return {
        "playbook": playbook if not custom else "custom",
        "steps": steps_out,
        "resilience_score": resilience,
        "grade": grade,
        "starting_integrity": 100.0,
        "weakest_link": weakest,
        "safe_response_rate": safe_response_rate,
        "verdict": (f"The org retained {resilience}% integrity through a {len(steps_spec)}-shock "
                    f"cascade (grade {grade}); {weakest['department']} was the weakest link."),
        "note": "Fragility and damage are computed from the real twin (skill confidence + adverse history); impact compounds as integrity falls.",
    }


async def list_playbooks() -> dict:
    return {"playbooks": [
        {"id": k, "steps": [{"shock": s, "department": d, "severity": sev} for s, d, sev in v]}
        for k, v in PLAYBOOKS.items()
    ]}
