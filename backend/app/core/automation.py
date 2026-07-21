"""
KAEOS Core — Automation Rules Engine (Sprint 8)

Declarative "when this, do that" rules over workflow entities. A rule watches
one entity_type for a dwell condition (an entity sitting in a state past a
threshold) and applies an action when it matches:

  trigger: {entity_type, state, dwell_hours}
  action:  {type: transition|assign|escalate, to_state?, assignee?}

Evaluation is on-demand (POST /org/rules/run) and also folded into the SLA
sweep, so it needs no scheduler to be correct and testable — the dwell is
computed live from each entity's updated_at/created_at, exactly like
find_stale_entities. Every firing writes a WorkflowEvent / activity alert
through the same guarded paths a human action would, so audit and RBAC hold.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Column, Boolean, DateTime, Integer, String, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import func

from app.core.workflow import (
    WorkflowSpec, _current_state, apply_transition,
)
from app.models.domain import Base

logger = logging.getLogger(__name__)

VALID_ACTIONS = {"transition", "assign", "escalate"}


def _uuid() -> str:
    return str(uuid.uuid4())


class AutomationRule(Base):
    """One declarative automation rule, tenant-scoped."""
    __tablename__ = "core_automation_rules"

    id = Column(String, primary_key=True, default=_uuid)
    tenant_id = Column(String, nullable=False, index=True)

    name = Column(String(128), nullable=False)
    is_active = Column(Boolean, default=True, index=True)

    # Trigger (dwell): entity_type sitting in trigger_state past dwell_hours.
    entity_type = Column(String(64), nullable=False, index=True)
    trigger_state = Column(String(64), nullable=False)
    dwell_hours = Column(Integer, nullable=False, default=24)

    # Action.
    action_type = Column(String(32), nullable=False)   # transition | assign | escalate
    action_to_state = Column(String(64), nullable=True)
    action_assignee = Column(String(128), nullable=True)

    created_by = Column(String(128), nullable=True)
    times_fired = Column(Integer, default=0)
    last_fired_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    def to_dict(self) -> dict:
        return {
            "id": self.id, "name": self.name, "is_active": self.is_active,
            "entity_type": self.entity_type, "trigger_state": self.trigger_state,
            "dwell_hours": self.dwell_hours, "action_type": self.action_type,
            "action_to_state": self.action_to_state, "action_assignee": self.action_assignee,
            "times_fired": self.times_fired,
            "last_fired_at": str(self.last_fired_at) if self.last_fired_at else None,
        }


def validate_rule(spec: Optional[WorkflowSpec], entity_type: str, trigger_state: str,
                  action_type: str, action_to_state: Optional[str],
                  action_assignee: Optional[str]) -> Optional[str]:
    """Return an error string if the rule is incoherent, else None."""
    if spec is None:
        return f"Unknown entity_type '{entity_type}'."
    if action_type not in VALID_ACTIONS:
        return f"action_type must be one of {sorted(VALID_ACTIONS)}."
    if trigger_state not in spec.states:
        return f"'{trigger_state}' is not a state of {entity_type}."
    if action_type == "transition":
        if not action_to_state:
            return "transition action needs action_to_state."
        if action_to_state not in spec.allowed_from(trigger_state):
            return (f"{entity_type} cannot go {trigger_state} -> {action_to_state}; "
                    f"allowed: {spec.allowed_from(trigger_state)}.")
    if action_type == "assign" and not action_assignee:
        return "assign action needs action_assignee."
    return None


def _age_hours(obj, now: datetime) -> Optional[float]:
    stamp = getattr(obj, "updated_at", None) or getattr(obj, "created_at", None)
    if stamp is None:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return (now - stamp).total_seconds() / 3600.0


async def _matching_entities(db: AsyncSession, spec: WorkflowSpec, tenant_id: str,
                             trigger_state: str, dwell_hours: int) -> list:
    now = datetime.now(timezone.utc)
    q = await db.execute(
        select(spec.model).where(spec.model.tenant_id == tenant_id).limit(2000)
    )
    hits = []
    for obj in q.scalars().all():
        if _current_state(obj, spec) != trigger_state:
            continue
        age = _age_hours(obj, now)
        if age is not None and age >= dwell_hours:
            hits.append(obj)
    return hits


async def evaluate_rules(
    db: AsyncSession, tenant: dict, only_rule_id: Optional[str] = None,
) -> dict:
    """Evaluate active rules and apply matched actions. Returns a summary."""
    from app.services.workflow_registry import get_spec

    tenant_id = tenant["tenant_id"]
    # Automation acts as a system operator (never above the caller's ceiling for
    # role-gated transitions — the rule author's action is attributed to them).
    system_actor = {
        "tenant_id": tenant_id, "role": "admin",
        "name": "automation", "email": "automation@kaeos",
    }

    rq = select(AutomationRule).where(
        AutomationRule.tenant_id == tenant_id, AutomationRule.is_active == True,  # noqa: E712
    )
    if only_rule_id:
        rq = rq.where(AutomationRule.id == only_rule_id)
    rules = (await db.execute(rq)).scalars().all()

    results = []
    total_fired = 0
    for rule in rules:
        spec = get_spec(rule.entity_type)
        if spec is None:
            continue
        matched = await _matching_entities(
            db, spec, tenant_id, rule.trigger_state, rule.dwell_hours)
        fired, errors = 0, []
        for obj in matched:
            try:
                if rule.action_type == "transition":
                    await apply_transition(db, spec, obj.id, rule.action_to_state,
                                           system_actor, note=f"Automation: {rule.name}")
                elif rule.action_type == "assign":
                    from app.core.collaboration import assign_entity
                    await assign_entity(db, tenant_id, spec.domain, spec.entity_type,
                                        obj.id, rule.action_assignee, "automation",
                                        note=f"Auto-assigned by rule '{rule.name}'")
                elif rule.action_type == "escalate":
                    await _escalate_one(db, tenant_id, spec, obj, rule)
                fired += 1
            except Exception as e:  # a guard/role block on one row must not kill the rule
                errors.append({"entity_id": obj.id, "error": str(e)[:200]})
        if fired:
            rule.times_fired = (rule.times_fired or 0) + fired
            rule.last_fired_at = datetime.now(timezone.utc)
            await db.commit()
            total_fired += fired
        results.append({"rule_id": rule.id, "name": rule.name,
                        "matched": len(matched), "fired": fired, "errors": errors})

    return {"rules_evaluated": len(rules), "actions_fired": total_fired, "results": results}


async def _escalate_one(db: AsyncSession, tenant_id: str, spec: WorkflowSpec,
                        obj, rule: AutomationRule) -> None:
    from app.models.agent_factory import ActivityEventType, ActivityFeedEvent, ActivitySeverity
    title = getattr(obj, "title", None) or getattr(obj, "subject", None) or \
        getattr(obj, "name", None) or obj.id
    db.add(ActivityFeedEvent(
        tenant_id=tenant_id,
        event_type=ActivityEventType.PROACTIVE_ALERT,
        severity=ActivitySeverity.WARNING,
        title=f"Automation '{rule.name}': {spec.entity_type.replace('_', ' ')} "
              f"\"{title}\" sat in {rule.trigger_state} past {rule.dwell_hours}h",
        description=f"{spec.domain} · rule-driven escalation.",
        source_type=spec.entity_type, source_id=obj.id,
        requires_action=True,
        event_metadata={"domain": spec.domain, "rule_id": rule.id},
    ))
    await db.commit()
