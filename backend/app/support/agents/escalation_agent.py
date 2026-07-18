"""KAEOS Support Domain - Escalation Agent

Context-grounding: the agent loads the real entity and reasons over its
content. Passing only an opaque id left the model classifying an identifier
(confirmed ungrounded on real onboarded data), so facts are non-optional.
"""
from typing import Any, Dict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.support.agents.gated_runner import run_gated_support_skill
from app.support.models.tickets import Ticket
from app.services.json_utils import plain_facts


class EscalationAgent:
    async def escalate_ticket(self, db: AsyncSession, ticket_id: str, tenant_id: str) -> Dict[str, Any]:
        ticket = (await db.execute(
            select(Ticket).where(Ticket.id == ticket_id, Ticket.tenant_id == tenant_id)
        )).scalar_one_or_none()
        if not ticket:
            raise ValueError(f"Ticket {ticket_id} not found")

        facts = {
            "subject": ticket.subject,
            "description": (ticket.description or "")[:1500],
            "priority": ticket.priority.value if ticket.priority else None,
            "status": ticket.status.value if ticket.status else None,
        }
        facts = plain_facts(facts)
        return await run_gated_support_skill(
            skill_id="support_escalation",
            steps=[{"step": 1, "name": "Escalate",
                    "prompt": f"Decide the escalation path for this ticket: {facts}"}],
            context={
                "ticket_id": ticket_id, "tenant_id": tenant_id, **facts,
                "instruction": "Output strict JSON: {escalate, target_tier, urgency, rationale}.",
            },
            tenant_id=tenant_id,
        )
