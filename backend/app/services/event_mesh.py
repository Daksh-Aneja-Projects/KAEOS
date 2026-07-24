"""Event Mesh — correlate an external signal to the twin and choose a governed response.

Correlation is grounded in the tenant's REAL twin: the signal's text is matched
against the departments that actually have skills and against skill ids, plus a
kind→department prior. The response is governed and real: a BRIEFING or a HITL is
written to the activity feed; a MISSION spins up the cross-domain mission engine.
Nothing is fabricated — an uncorrelated signal gets no response.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import Skill
from app.models.event_mesh import ExternalSignal

logger = logging.getLogger(__name__)

# Which department a signal kind most concerns (a prior, refined by text match).
_KIND_DEPT = {
    "REGULATORY": "legal", "SECURITY": "engineering", "VENDOR": "operations",
    "SUPPLY_CHAIN": "operations", "MARKET": "finance", "NEWS": None,
}

# KAEOS is a fixed 7-domain platform; these canonical departments always exist in
# the twin. Skill departments may be tagged with aliases, normalized here.
_CANON = ["finance", "hr", "sales", "support", "operations", "legal", "engineering", "marketing"]
_ALIAS = {
    "human_resources": "hr", "people": "hr", "workforce": "hr",
    "customer_support": "support", "customersupport": "support", "cx": "support", "service": "support",
    "ops": "operations", "supply_chain": "operations", "procurement": "operations",
    "eng": "engineering", "platform": "engineering", "it": "engineering",
    "revenue": "sales", "gtm": "sales", "growth": "marketing", "demand_gen": "marketing",
    "compliance": "legal", "risk_legal": "legal",
}
# Text tokens that map a phrase to a canonical department.
_DEPT_TEXT = {
    "finance": ["finance", "financial", "budget", "invoice", "reporting"],
    "hr": ["hr", "human resources", "employee", "hiring", "headcount", "payroll"],
    "sales": ["sales", "pipeline", "deal", "revenue"],
    "support": ["support", "customer support", "ticket", "service desk"],
    "operations": ["operations", "ops", "supply chain", "vendor", "supplier", "logistics", "procurement"],
    "legal": ["legal", "compliance", "regulation", "regulatory", "contract", "gdpr", "sec ", "disclosure"],
    "engineering": ["engineering", "security", "cve", "vulnerability", "deploy", "infrastructure", "outage", "system"],
    "marketing": ["marketing", "campaign", "brand"],
}


def _canon_dept(raw: str) -> str:
    r = (raw or "").lower().strip()
    return _ALIAS.get(r, r)


async def _twin_departments(db: AsyncSession, tenant_id: str) -> dict[str, list[str]]:
    """The org's canonical departments -> their skill ids. The 7 governed domains
    always exist; skills add specificity and are normalized to canonical names."""
    rows = (await db.execute(
        select(Skill.department, Skill.skill_id).where(
            Skill.tenant_id == tenant_id, Skill.status == "ACTIVE")
    )).all()
    out: dict[str, list[str]] = {d: [] for d in _CANON}
    for dept, sid in rows:
        out.setdefault(_canon_dept(dept), []).append(sid)
    return out


async def correlate(db: AsyncSession, tenant_id: str, signal: ExternalSignal) -> ExternalSignal:
    """Match the signal to real twin entities and choose a governed response kind."""
    depts = await _twin_departments(db, tenant_id)
    text = f"{signal.title} {signal.body or ''}".lower()

    matched: list[dict] = []

    # 1) kind prior: if the concerned department exists in the twin, it matches.
    prior = _KIND_DEPT.get(signal.kind)
    if prior and prior in depts:
        matched.append({"type": "department", "name": prior, "via": "kind"})

    # 2) text match against canonical department vocab and skill ids.
    for dept, skills in depts.items():
        if dept != prior and any(tok in text for tok in _DEPT_TEXT.get(dept, [dept])):
            matched.append({"type": "department", "name": dept, "via": "text"})
        for sid in skills:
            token = sid.replace("_", " ")
            if token and token in text:
                matched.append({"type": "skill", "name": sid, "via": "text"})

    # De-dup.
    seen = set()
    matched = [m for m in matched if not (f"{m['type']}:{m['name']}" in seen or seen.add(f"{m['type']}:{m['name']}"))]
    signal.matched_entities = matched

    if not matched:
        signal.status = "CORRELATED"
        signal.response_kind = "NONE"
        signal.correlation_note = "No twin entity matched this signal; logged for awareness, no action."
        return signal

    names = ", ".join(m["name"] for m in matched[:5])
    signal.status = "CORRELATED"
    # Decide the governed response from severity + match strength.
    if signal.severity == "critical":
        signal.response_kind = "MISSION" if len({m["name"] for m in matched if m["type"] == "department"}) >= 2 else "HITL"
        signal.correlation_note = f"Critical signal touches {names}; escalating for governed response."
    elif signal.severity == "warning":
        signal.response_kind = "BRIEFING"
        signal.correlation_note = f"Signal affects {names}; briefing the owning team."
    else:
        signal.response_kind = "BRIEFING"
        signal.correlation_note = f"Informational signal related to {names}."
    return signal


async def respond(db: AsyncSession, tenant_id: str, signal: ExternalSignal) -> ExternalSignal:
    """Enact the governed response the correlation chose."""
    if signal.response_kind == "NONE" or signal.status == "RESPONDED":
        signal.status = "RESPONDED"
        signal.responded_at = datetime.now(timezone.utc)
        return signal

    dept_matches = [m["name"] for m in (signal.matched_entities or []) if m["type"] == "department"]

    if signal.response_kind == "MISSION":
        try:
            from app.services.missions import plan_mission
            goal = f"Respond to {signal.kind.lower()} signal: {signal.title}"
            mission = await plan_mission(db, tenant_id=tenant_id, goal=goal, created_by="event-mesh")
            signal.response_ref = mission.id
        except Exception as e:
            logger.warning(f"[event-mesh] mission spawn failed, falling back to HITL: {e}")
            signal.response_kind = "HITL"

    if signal.response_kind in ("BRIEFING", "HITL"):
        await _emit_activity(
            tenant_id, signal,
            requires_action=(signal.response_kind == "HITL"))

    signal.status = "RESPONDED"
    signal.responded_at = datetime.now(timezone.utc)
    return signal


async def _emit_activity(tenant_id: str, signal: ExternalSignal, *, requires_action: bool) -> None:
    """Write the briefing/HITL to the real activity feed. Never fatal."""
    try:
        from app.services.activity_feed import ActivityFeedService
        from app.models.agent_factory import ActivityEventType, ActivitySeverity
        sev = ActivitySeverity.ACTION_REQUIRED if requires_action else (
            ActivitySeverity.WARNING if signal.severity == "warning" else ActivitySeverity.INFO)
        await ActivityFeedService().emit(
            event_type=ActivityEventType.EXTERNAL_SIGNAL,
            title=f"{signal.kind} signal: {signal.title}",
            description=signal.correlation_note or "",
            tenant_id=tenant_id, severity=sev,
            source_type="event_mesh", source_id=signal.id,
            requires_action=requires_action,
        )
    except Exception as e:  # pragma: no cover
        logger.debug(f"[event-mesh] activity emit skipped: {e}")
