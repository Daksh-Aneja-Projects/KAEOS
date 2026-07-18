"""KAEOS Support Domain — Triage Agent"""
import logging
from typing import Any, Dict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.support.agents.gated_runner import run_gated_support_skill
from app.support.models.tickets import Ticket
from app.services.json_utils import plain_facts

logger = logging.getLogger(__name__)


class TriageAgent:
    async def triage_ticket(self, db: AsyncSession, ticket_id: str, tenant_id: str) -> Dict[str, Any]:
        logger.info(f"TriageAgent triaging ticket {ticket_id}")

        # Load the ticket's real content into context. Passing only the id left
        # the model classifying an opaque identifier — the triage was ungrounded,
        # confirmed by running it over real onboarded tickets (it never saw the
        # subject/description). The classifier must reason over the actual text.
        ticket = (await db.execute(
            select(Ticket).where(Ticket.id == ticket_id, Ticket.tenant_id == tenant_id)
        )).scalar_one_or_none()
        if not ticket:
            raise ValueError(f"Ticket {ticket_id} not found")

        facts = {
            "subject": ticket.subject,
            "description": (ticket.description or "")[:1500],
            "current_priority": ticket.priority.value if ticket.priority else None,
            "current_status": ticket.status.value if ticket.status else None,
        }
        facts = plain_facts(facts)
        steps = [
            {"step": 1, "name": "Classify",
             "prompt": f"Classify this ticket's severity and category from its content: {facts}"},
            {"step": 2, "name": "Assign Queue",
             "prompt": "Recommend the queue and priority based on the classification."},
        ]
        context = {
            "ticket_id": ticket_id, "tenant_id": tenant_id,
            **facts,
            "instruction": "Output strict JSON: {severity, category, recommended_priority, queue}.",
        }
        return await run_gated_support_skill(
            skill_id="support_triage", steps=steps, context=context, tenant_id=tenant_id,
        )
