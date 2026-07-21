"""
KAEOS Support — Analytics Service
Backlog composition, resolution speed and first-response coverage, computed
live from ticket timestamps (never from cached counters).
"""
from datetime import datetime, timezone

from sqlalchemy import func as sqlfunc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.support.models.tickets import Ticket, TicketStatus

_OPEN = [TicketStatus.NEW, TicketStatus.ASSIGNED, TicketStatus.OPEN,
         TicketStatus.PENDING_CUSTOMER]


def _hours_between(start, end) -> float:
    if start is None or end is None:
        return 0.0
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    return max((end - start).total_seconds() / 3600.0, 0.0)


async def support_analytics(db: AsyncSession, tenant_id: str) -> dict:
    status_q = await db.execute(
        select(Ticket.status, sqlfunc.count())
        .where(Ticket.tenant_id == tenant_id)
        .group_by(Ticket.status)
    )
    status_counts = {(s.value if hasattr(s, "value") else str(s)): int(c) for s, c in status_q.all()}

    prio_q = await db.execute(
        select(Ticket.priority, sqlfunc.count())
        .where(Ticket.tenant_id == tenant_id, Ticket.status.in_(_OPEN))
        .group_by(Ticket.priority)
    )
    prio_counts = [{"label": (p.value if hasattr(p, "value") else str(p)), "value": int(c)}
                   for p, c in prio_q.all()]

    backlog = sum(status_counts.get(s.value, 0) for s in _OPEN)
    total = sum(status_counts.values())

    # Resolution + first-response speed: computed in Python from timestamps so
    # it works identically on SQLite and Postgres (no dialect-specific date math).
    resolved_q = await db.execute(
        select(Ticket.created_at, Ticket.first_response_at, Ticket.resolved_at)
        .where(Ticket.tenant_id == tenant_id, Ticket.resolved_at.isnot(None))
        .order_by(Ticket.resolved_at.desc())
        .limit(500)
    )
    rows = resolved_q.all()
    res_hours = [_hours_between(c, r) for c, _, r in rows if r is not None]
    fr_hours = [_hours_between(c, f) for c, f, _ in rows if f is not None]
    avg_resolution = sum(res_hours) / len(res_hours) if res_hours else None
    avg_first_response = sum(fr_hours) / len(fr_hours) if fr_hours else None

    unassigned_q = await db.execute(
        select(sqlfunc.count())
        .where(Ticket.tenant_id == tenant_id,
               Ticket.status.in_(_OPEN),
               Ticket.assigned_agent_id.is_(None))
    )
    unassigned = int(unassigned_q.scalar() or 0)

    urgent_open_q = await db.execute(
        select(sqlfunc.count())
        .where(Ticket.tenant_id == tenant_id, Ticket.status.in_(_OPEN),
               Ticket.priority == "URGENT")
    )
    urgent_open = int(urgent_open_q.scalar() or 0)

    insights = []
    if urgent_open:
        insights.append({"severity": "critical",
                         "message": f"{urgent_open} URGENT tickets are still open."})
    if unassigned:
        insights.append({"severity": "warning",
                         "message": f"{unassigned} open tickets have no assigned agent."})
    if avg_first_response is not None and avg_first_response > 24:
        insights.append({"severity": "warning",
                         "message": f"Average first response is {avg_first_response:.1f}h — over the 24h target."})
    if not insights:
        insights.append({"severity": "info", "message": "Support queue is healthy."})

    return {
        "domain": "support",
        "kpis": [
            {"key": "backlog", "label": "Open Backlog", "value": backlog, "format": "number"},
            {"key": "total", "label": "Total Tickets", "value": total, "format": "number"},
            {"key": "resolved", "label": "Resolved", "value": status_counts.get("RESOLVED", 0) + status_counts.get("CLOSED", 0), "format": "number"},
            {"key": "mttr", "label": "Avg Resolution", "value": avg_resolution, "format": "hours"},
            {"key": "frt", "label": "Avg First Response", "value": avg_first_response, "format": "hours"},
            {"key": "unassigned", "label": "Unassigned Open", "value": unassigned, "format": "number"},
        ],
        "charts": [
            {"key": "status_mix", "title": "Tickets by Status", "type": "donut",
             "items": [{"label": k, "value": v} for k, v in status_counts.items()]},
            {"key": "open_priority", "title": "Open Backlog by Priority", "type": "bar", "items": prio_counts},
        ],
        "insights": insights,
    }
