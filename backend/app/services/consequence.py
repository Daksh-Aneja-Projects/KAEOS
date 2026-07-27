"""Single source of truth for high-consequence (always-HITL) detection.

A high-consequence action (payment, termination, contract execution, external
send, data deletion) ALWAYS routes to a human at Gate 3, regardless of
confidence. Both enforcement sites (app/agents/runtime.py Gate 3 and the
/skills/{id}/execute route) call is_high_consequence(); the previous inline
substring-blob implementations were duplicated and could drift apart.

Detection order:
  1. The explicit ``always_hitl`` field on the Skill - authoritative. An
     explicitly flagged skill can NEVER be de-escalated by naming or tags.
  2. Tag/name inference over compliance tags, tags, department and skill_id
     (HIGH_CONSEQUENCE_TAGS) - a fallback that can only ESCALATE, kept so
     legacy skills without the explicit flag stay safe.
"""
from typing import Any

from app.core.config import get_settings


def is_high_consequence(skill: Any) -> bool:
    """True when this skill must always route to a human, regardless of
    confidence. Accepts a Skill ORM object or the executor's skill dict."""
    if skill is None:
        return False
    if isinstance(skill, dict):
        def get(key, default=None):
            return skill.get(key, default)
    else:
        def get(key, default=None):
            return getattr(skill, key, default)

    # 1. Explicit flag: authoritative, never de-escalated.
    if bool(get("always_hitl", False)):
        return True

    # 2. Naming-convention inference: escalate-only fallback.
    parts = list(get("compliance_tags") or []) + list(get("tags") or [])
    for key in ("department", "skill_id"):
        val = get(key)
        if val:
            parts.append(str(val))
    blob = " ".join(str(x).lower() for x in parts)
    return any(t in blob for t in get_settings().HIGH_CONSEQUENCE_TAGS)
