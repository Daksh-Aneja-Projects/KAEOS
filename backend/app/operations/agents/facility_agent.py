"""
KAEOS Operations Domain — Facility Agent
"""
import logging
from typing import Dict, Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.operations.agents.gated_runner import extract_decision, run_gated_operations_skill
from app.operations.models.facilities import WorkOrder
from app.services.json_utils import plain_facts

logger = logging.getLogger(__name__)

class FacilityAgent:
    """Agent for monitoring facilities and prioritizing work orders."""

    def __init__(self):
        pass

    # Safety keywords that force URGENT regardless of a (possibly missing or
    # mislabeled) severity field. A work order with no severity should never be
    # quietly triaged to MEDIUM when its title says "gas leak".
    _SAFETY_KEYWORDS = ("gas leak", "fire", "smoke", "flood", "electrical", "shock",
                        "carbon monoxide", "asbestos", "collapse", "no power", "burst")
    _URGENT_SEVERITIES = ("CRITICAL", "HIGH", "URGENT", "SEV1", "SEV2", "P0", "P1", "EMERGENCY")

    async def prioritize_work_order(self, request_data: Dict[str, Any]) -> Dict[str, Any]:
        """Calculates facility maintenance priorities from severity, keywords, and occupant impact."""
        title = (request_data.get("issue_title") or "")
        logger.info(f"FacilityAgent prioritizing work order: {title}")

        raw = request_data.get("severity")
        severity = str(raw).upper() if raw is not None else "UNKNOWN"
        title_l = title.lower()

        safety = any(k in title_l for k in self._SAFETY_KEYWORDS)
        if safety or severity in self._URGENT_SEVERITIES:
            priority, hours = "URGENT", 2
        elif severity in ("MEDIUM", "MODERATE", "SEV3", "P2"):
            priority, hours = "MEDIUM", 8
        elif severity in ("LOW", "SEV4", "P3", "P4"):
            priority, hours = "LOW", 24
        else:
            # Unknown/unrecognized severity is NOT assumed low — route to a human
            # to classify rather than silently defaulting a possibly-critical order.
            priority, hours = "NEEDS_TRIAGE", 4

        return {
            "issue_title": title,
            "assigned_team": "Maintenance Lead",
            "priority": priority,
            "scheduled_hours": hours,
            "safety_flagged": safety,
        }

    async def triage_work_order(self, db: AsyncSession, work_order_id: str, tenant_id: str) -> Dict[str, Any]:
        """Load a real WorkOrder, deterministically triage it, and route the
        one ITGC control that matches its category through the gated 7-gate
        pipeline with real, DB-backed context:
          MAINTENANCE  -> CHANGE_MANAGEMENT   (is_production/implementer/approver/ticket)
          SAFETY       -> INCIDENT_POSTMORTEM (severity/status/root_cause/action_items)
          DECOMMISSION -> BACKUP_RETENTION    (backup_verified/record_age_days/retention_days)
        The other two checkers see no matching context key and correctly
        return NOT_APPLICABLE rather than a fabricated verdict.
        """
        wo = (await db.execute(
            select(WorkOrder).where(WorkOrder.id == work_order_id, WorkOrder.tenant_id == tenant_id)
        )).scalar_one_or_none()
        if not wo:
            raise ValueError(f"Work order {work_order_id} not found")

        # Deterministic triage FIRST (the pure, unit-tested function above) —
        # the priority a human sees is never an LLM guess, and it is persisted
        # regardless of how the compliance gate below resolves.
        triage = await self.prioritize_work_order({"issue_title": wo.issue_title, "severity": wo.severity})
        wo.priority = triage["priority"]
        wo.assigned_team = triage["assigned_team"]
        wo.scheduled_hours = float(triage["scheduled_hours"])
        wo.safety_flagged = bool(triage["safety_flagged"])

        category = (wo.category or "MAINTENANCE").upper()
        context_extra: Dict[str, Any] = {}
        if category == "MAINTENANCE":
            context_extra["change"] = {
                "is_production": wo.is_production, "implementer": wo.implementer,
                "approver": wo.approver, "ticket": wo.change_ticket,
            }
        elif category == "SAFETY":
            action_items = [ln.strip() for ln in (wo.action_items or "").split("\n") if ln.strip()]
            context_extra["incident"] = {
                "severity": wo.severity, "status": (wo.status or "").lower(),
                "postmortem": {"root_cause": wo.root_cause, "action_items": action_items},
            }
        elif category == "DECOMMISSION":
            context_extra["retention"] = {
                "operation": "delete", "record_age_days": wo.record_age_days,
                "retention_days": wo.retention_days, "backup_verified": wo.backup_verified,
            }

        facts = plain_facts({
            "facility_name": wo.facility_name, "issue_title": wo.issue_title,
            "category": category, "status": wo.status, "priority": wo.priority,
        })
        result = await run_gated_operations_skill(
            skill_id="operations_work_order_triage",
            steps=[{"step": 1, "name": "Triage",
                    "prompt": f"Assess this facility work order and recommend the next step: {facts}"}],
            context={
                "work_order_id": work_order_id, "tenant_id": tenant_id, **facts, **context_extra,
                "instruction": "Output strict JSON: {risk_assessment, recommended_next_step}.",
            },
            tenant_id=tenant_id,
            compliance_tags=["SOC2", "INTERNAL_CONTROL", "CHANGE_MANAGEMENT",
                             "INCIDENT_POSTMORTEM", "BACKUP_RETENTION"],
        )

        if result.get("status") == "SUCCESS_CLEAN":
            decision = extract_decision(result)
            note_parts = []
            risk = decision.get("risk_assessment")
            if risk:
                note_parts.append(str(risk).rstrip(".") + ".")
            step = decision.get("recommended_next_step")
            if step:
                note_parts.append(f"Next step: {step}.")
            wo.ai_notes = " ".join(note_parts) if note_parts else None
            result = {**result, "decision": decision}

        db.add(wo)
        await db.commit()
        result["work_order_id"] = work_order_id
        result["priority"] = wo.priority
        result["assigned_team"] = wo.assigned_team
        result["safety_flagged"] = wo.safety_flagged
        return result
