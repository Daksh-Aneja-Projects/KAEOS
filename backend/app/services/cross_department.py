"""H12: cross-department automations over the internal event bus.

The ten departments were islands — they published and consumed no internal
events, so an action in one never became governed work in another. With the bus
wired (H8), these in-process handlers turn one department's action into another's
governed work:

  * HR offboarding completed  -> a governed IT-deprovision MISSION (engineering
    revokes access under the 7 gates, not a silent background write);
  * a lending adverse-action  -> a fair-lending review item for compliance/legal;
  * a support escalation      -> an operations awareness signal.

Each handler owns its own DB session (it runs fire-and-forget off the emit) and
is best-effort: a reaction failing must never unwind the originating action.
register_cross_department_automations() is called once at startup.
"""
import logging

logger = logging.getLogger(__name__)


async def _on_employee_offboarded(event_data: dict) -> None:
    payload = event_data.get("payload") or {}
    tenant_id = event_data.get("tenant_id")
    who = payload.get("employee_id") or "a departing employee"
    if not tenant_id:
        return
    try:
        from app.core.database import AsyncSessionLocal
        from app.services.missions import plan_mission
        async with AsyncSessionLocal() as db:
            # plan_mission commits its own mission + steps; do NOT re-commit
            # (double-commit trips the StaticPool single-connection StaleData).
            await plan_mission(
                db, tenant_id=tenant_id,
                goal=(f"Deprovision IT access and revoke system entitlements for "
                      f"offboarded employee {who}"),
                created_by="event-mesh")
        logger.info("[x-dept] offboarding of %s -> IT deprovision mission (%s)",
                    who, tenant_id)
    except Exception as e:
        logger.warning("[x-dept] offboarding -> deprovision mission failed: %s", e)


async def _on_lending_adverse_action(event_data: dict) -> None:
    payload = event_data.get("payload") or {}
    tenant_id = event_data.get("tenant_id")
    if not tenant_id:
        return
    app_no = payload.get("application_number") or payload.get("application_id") or "?"
    try:
        from app.core.database import AsyncSessionLocal
        from app.models.event_mesh import ExternalSignal
        async with AsyncSessionLocal() as db:
            db.add(ExternalSignal(
                tenant_id=tenant_id, kind="REGULATORY",
                title=f"Fair-lending review: adverse-action notice issued ({app_no})",
                body=("A lending denial issued a Reg B adverse-action notice. Logged "
                      "as a fair-lending oversight item for compliance/legal review."),
                source="lending", severity="warning",
                authority_score=0.9, status="NEW"))
            await db.commit()
        logger.info("[x-dept] adverse-action %s -> compliance review item (%s)",
                    app_no, tenant_id)
    except Exception as e:
        logger.warning("[x-dept] adverse-action -> compliance review failed: %s", e)


async def _on_support_ticket_escalated(event_data: dict) -> None:
    payload = event_data.get("payload") or {}
    tenant_id = event_data.get("tenant_id")
    if not tenant_id:
        return
    ticket = payload.get("ticket_id") or "?"
    try:
        from app.core.database import AsyncSessionLocal
        from app.models.event_mesh import ExternalSignal
        async with AsyncSessionLocal() as db:
            db.add(ExternalSignal(
                tenant_id=tenant_id, kind="VENDOR",
                title=f"Operations awareness: support ticket {ticket} escalated",
                body=("Support escalated a ticket that could not be resolved within its "
                      "team. Surfaced to operations so systemic load/quality issues are "
                      "visible across departments."),
                source="support", severity="info",
                authority_score=0.6, status="NEW"))
            await db.commit()
        logger.info("[x-dept] support escalation %s -> operations signal (%s)",
                    ticket, tenant_id)
    except Exception as e:
        logger.warning("[x-dept] support escalation -> operations signal failed: %s", e)


def register_cross_department_automations() -> None:
    """Wire the department reactions onto the bus. Idempotent (EventBus.on is)."""
    from app.services.event_bus import EventBus, EventType
    EventBus.on(EventType.EMPLOYEE_OFFBOARDED, _on_employee_offboarded)
    EventBus.on(EventType.LENDING_ADVERSE_ACTION, _on_lending_adverse_action)
    EventBus.on(EventType.SUPPORT_TICKET_ESCALATED, _on_support_ticket_escalated)
    logger.info("[x-dept] cross-department automations registered (3)")
