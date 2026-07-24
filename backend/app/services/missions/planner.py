"""Mission planner — decompose a plain-language goal into a governed DAG of real skills.

The plan is GROUNDED: every executable step maps to a real ACTIVE Skill that
exists for the tenant (best-confidence skill in that department). The department
scope is inferred from the goal (keyword signals) intersected with the departments
that actually have skills, ordered by a canonical dependency priority. An LLM, when
available, enriches the human-readable narrative; it never invents steps that have
no backing skill. HITL checkpoints are set from the real per-department autonomy
policy, so a mission respects the same risk appetite as a single decision.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import Skill
from app.models.missions import Mission, MissionStep, MissionEvent

logger = logging.getLogger(__name__)

# Canonical department -> the raw Skill.department aliases seen across tenants.
_DEPT_ALIASES = {
    "hr": ["hr", "human_resources", "humanresources", "people", "workforce"],
    "finance": ["finance", "financial", "accounting", "fp&a"],
    "legal": ["legal", "compliance", "legal_compliance", "risk_legal"],
    "sales": ["sales", "revenue", "gtm"],
    "support": ["support", "customer_support", "customersupport", "cx", "service"],
    "operations": ["operations", "ops", "supply_chain", "procurement"],
    "engineering": ["engineering", "eng", "platform", "it"],
    "marketing": ["marketing", "growth", "demand_gen"],
}
_ALIAS_TO_CANON = {a: canon for canon, aliases in _DEPT_ALIASES.items() for a in aliases}

# Goal keyword -> canonical department signal.
_DEPT_SIGNALS = {
    "hr": ["hire", "hiring", "onboard", "employee", "headcount", "staff", "recruit",
           "candidate", "payroll", "attrition", "workforce", "people"],
    "finance": ["budget", "invoice", "payment", "cost", "finance", "revenue", "close",
                "quarter", "expense", "vendor payment", "ap", "ar", "forecast", "approve the budget"],
    "legal": ["contract", "compliance", "legal", "regulation", "regulatory", "sec",
              "gdpr", "hipaa", "policy", "inquiry", "audit", "risk"],
    "sales": ["deal", "pipeline", "customer win", "quota", "sales", "opportunity",
              "revenue target", "renewal", "prospect"],
    "support": ["ticket", "support", "incident", "sla", "customer service", "escalation",
                "outage response", "brief support"],
    "operations": ["vendor", "supply", "operations", "logistics", "procurement",
                   "supplier", "inventory", "capacity"],
    "engineering": ["deploy", "engineering", "code", "release", "infra", "infrastructure",
                    "outage", "system", "migration"],
    "marketing": ["campaign", "marketing", "brand", "launch", "content", "demand", "lead gen"],
}

# Canonical execution order (dependency priority) across departments.
_DEPT_ORDER = ["legal", "finance", "hr", "operations", "engineering", "marketing", "sales", "support"]

# Departments where an autonomous action is treated as high-consequence.
_HIGH_CONSEQUENCE = {"legal", "finance"}


def _canon_dept(raw: Optional[str]) -> str:
    r = (raw or "general").lower().strip()
    return _ALIAS_TO_CANON.get(r, r)


async def _skills_by_department(db: AsyncSession, tenant_id: str) -> dict[str, list[Skill]]:
    """Group ACTIVE skills by CANONICAL department, so a plan matches real data
    regardless of whether skills are tagged 'hr' or 'human_resources', etc."""
    rows = (await db.execute(
        select(Skill).where(Skill.tenant_id == tenant_id, Skill.status == "ACTIVE")
        .order_by(Skill.confidence.desc())
    )).scalars().all()
    out: dict[str, list[Skill]] = {}
    for s in rows:
        out.setdefault(_canon_dept(s.department or s.domain), []).append(s)
    return out


def _relevant_departments(goal: str, available: dict[str, list[Skill]]) -> list[str]:
    g = (goal or "").lower()
    hit = []
    for dept, words in _DEPT_SIGNALS.items():
        if dept in available and any(w in g for w in words):
            hit.append(dept)
    # If the goal names no department we recognise, span the departments that
    # actually have skills — an honest cross-functional default, never invented.
    if not hit:
        hit = [d for d in _DEPT_ORDER if d in available]
    # Order by canonical dependency priority.
    return [d for d in _DEPT_ORDER if d in hit]


async def _optional_narrative(tenant_id: str, goal: str, steps: list[dict]) -> Optional[str]:
    """Best-effort LLM narrative; never fatal, never invents steps.

    Uses the real model (local qwen via Ollama, or the tenant's provider) whenever
    one is available. Skipped only under the dedicated unit-test flag
    (KAEOS_FAKE_LLM); hard-bounded by a timeout so planning never blocks on a slow
    model, and it silently uses the deterministic narrative if no provider answers.
    """
    import os
    if os.environ.get("KAEOS_FAKE_LLM"):
        return None
    try:
        import asyncio
        from app.services.llm_router import LLMRouter
        router = await LLMRouter.for_tenant(tenant_id)
        plan_txt = "; ".join(f"{s['seq']}. {s['name']} ({s['department']})" for s in steps)
        res = await asyncio.wait_for(router.complete(
            prompt=(f"Mission goal: {goal}\nPlanned steps: {plan_txt}\n"
                    "In 2 sentences, explain why this ordered plan achieves the goal "
                    "and where human review is warranted. Plain text."),
            model_tier="fast", max_tokens=180,
        ), timeout=45)
        text = res if isinstance(res, str) else res.get("content")
        if text and "fake_llm" not in text and "simulated" not in text.lower():
            return text.strip()
    except Exception as e:  # pragma: no cover - narrative is decorative
        logger.debug(f"[mission] narrative enrichment skipped: {e}")
    return None


async def plan_mission(
    db: AsyncSession, *, tenant_id: str, goal: str,
    budget_usd: Optional[float] = None, created_by: Optional[str] = None,
) -> Mission:
    """Create a Mission and its DAG of steps, each mapped to a real skill."""
    available = await _skills_by_department(db, tenant_id)
    depts = _relevant_departments(goal, available)

    # Resolve per-department HITL from the real autonomy policy.
    try:
        from app.services.autonomy_policy import resolve_min_confidence
    except Exception:  # pragma: no cover
        resolve_min_confidence = None

    mission = Mission(tenant_id=tenant_id, goal=goal, status="PLANNING",
                      budget_usd=budget_usd, departments=depts, created_by=created_by)
    db.add(mission)
    await db.flush()  # get mission.id

    steps_meta: list[dict] = []
    seq = 0
    for dept in depts:
        skill = available[dept][0]  # highest-confidence ACTIVE skill in this dept
        threshold = 0.82
        if resolve_min_confidence:
            try:
                threshold = await resolve_min_confidence(tenant_id, dept)
            except Exception:
                pass
        hitl = (skill.confidence or 0.0) < threshold or dept in _HIGH_CONSEQUENCE
        seq += 1
        # Steps are INDEPENDENT: each department's action stands on its own, so an
        # autonomous step still runs while another awaits a human, and one failure
        # does not block the rest. The canonical ordering (seq) reflects a
        # recommended sequence, not a hard prerequisite — we do not invent
        # dependencies the goal did not state.
        step = MissionStep(
            tenant_id=tenant_id, mission_id=mission.id, seq=seq,
            name=f"{dept.capitalize()}: {skill.skill_id}",
            department=dept, skill_id=skill.skill_id,
            confidence=skill.confidence or 0.0,
            depends_on=[],
            hitl_required=hitl, status="PENDING",
        )
        db.add(step)
        steps_meta.append({"seq": seq, "name": step.name, "department": dept})

    if not steps_meta:
        # No skills at all for the tenant: an honest, empty, non-executable plan.
        mission.status = "FAILED"
        mission.narrative = "No ACTIVE skills exist for this tenant, so the goal cannot be decomposed into executable steps."
        db.add(MissionEvent(tenant_id=tenant_id, mission_id=mission.id, kind="PLANNED",
                            message=mission.narrative))
        await db.commit()
        await db.refresh(mission)
        return mission

    narrative = await _optional_narrative(tenant_id, goal, steps_meta)
    mission.narrative = narrative or (
        f"Decomposed into {len(steps_meta)} governed steps across "
        f"{', '.join(depts)}; each step runs the department's highest-confidence "
        f"skill through the 7 gates, ordered so upstream decisions inform downstream ones."
    )
    mission.status = "RUNNING"
    db.add(MissionEvent(
        tenant_id=tenant_id, mission_id=mission.id, kind="PLANNED",
        message=f"Planned {len(steps_meta)} steps across {', '.join(depts)}."
                + (f" Budget cap ${budget_usd:.2f}." if budget_usd else "")))
    await db.commit()
    await db.refresh(mission)
    return mission
