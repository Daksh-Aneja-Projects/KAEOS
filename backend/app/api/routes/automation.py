"""
KAEOS — Automation Rules API (Sprint 8)

CRUD for declarative dwell-based rules plus an on-demand evaluation trigger.
Rules are validated against the workflow registry at creation time so an
incoherent rule (unknown entity, illegal transition) can never be stored.
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.tenant import get_tenant_id, require_role
from app.core.automation import AutomationRule, evaluate_rules, validate_rule
from app.services.workflow_registry import get_spec

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/org/rules", tags=["Automation"])


class RuleRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    entity_type: str = Field(..., min_length=1, max_length=64)
    trigger_state: str = Field(..., min_length=1, max_length=64)
    dwell_hours: int = Field(24, ge=0, le=8760)
    action_type: str = Field(..., pattern="^(transition|assign|escalate)$")
    action_to_state: Optional[str] = Field(None, max_length=64)
    action_assignee: Optional[str] = Field(None, max_length=128)
    is_active: bool = True


@router.get("")
async def list_rules(tenant_id: str = Depends(get_tenant_id),
                     db: AsyncSession = Depends(get_db)):
    q = await db.execute(
        select(AutomationRule).where(AutomationRule.tenant_id == tenant_id)
        .order_by(AutomationRule.created_at.desc())
    )
    return [r.to_dict() for r in q.scalars().all()]


@router.post("", status_code=201)
async def create_rule(body: RuleRequest,
                      tenant: dict = Depends(require_role("operator")),
                      db: AsyncSession = Depends(get_db)):
    spec = get_spec(body.entity_type)
    err = validate_rule(spec, body.entity_type, body.trigger_state,
                        body.action_type, body.action_to_state, body.action_assignee)
    if err:
        raise HTTPException(422, detail=err)
    rule = AutomationRule(
        tenant_id=tenant["tenant_id"], name=body.name, is_active=body.is_active,
        entity_type=body.entity_type, trigger_state=body.trigger_state,
        dwell_hours=body.dwell_hours, action_type=body.action_type,
        action_to_state=body.action_to_state, action_assignee=body.action_assignee,
        created_by=tenant.get("name"),
    )
    db.add(rule)
    await db.commit()
    await db.refresh(rule)
    return rule.to_dict()


@router.patch("/{rule_id}")
async def toggle_rule(rule_id: str, is_active: bool,
                      tenant: dict = Depends(require_role("operator")),
                      db: AsyncSession = Depends(get_db)):
    q = await db.execute(
        select(AutomationRule).where(AutomationRule.id == rule_id,
                                     AutomationRule.tenant_id == tenant["tenant_id"])
    )
    rule = q.scalar_one_or_none()
    if rule is None:
        raise HTTPException(404, detail="Rule not found")
    rule.is_active = is_active
    await db.commit()
    return rule.to_dict()


@router.delete("/{rule_id}")
async def delete_rule(rule_id: str,
                      tenant: dict = Depends(require_role("operator")),
                      db: AsyncSession = Depends(get_db)):
    q = await db.execute(
        select(AutomationRule).where(AutomationRule.id == rule_id,
                                     AutomationRule.tenant_id == tenant["tenant_id"])
    )
    rule = q.scalar_one_or_none()
    if rule is None:
        raise HTTPException(404, detail="Rule not found")
    await db.delete(rule)
    await db.commit()
    return {"deleted": True}


@router.post("/run")
async def run_rules(rule_id: Optional[str] = None,
                    tenant: dict = Depends(require_role("operator")),
                    db: AsyncSession = Depends(get_db)):
    """Evaluate all active rules now (or one, if rule_id given)."""
    return await evaluate_rules(db, tenant, only_rule_id=rule_id)
