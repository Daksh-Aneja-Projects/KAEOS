"""KAEOS Support Domain - Escalation Agent

Context-grounding: the agent loads the real entity and reasons over its
content. Passing only an opaque id left the model classifying an identifier
(confirmed ungrounded on real onboarded data), so facts are non-optional.
"""
from typing import Any, Dict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.support.agents.gated_runner import extract_decision, run_gated_support_skill
from app.support.models.escalation import EscalationEvent, EscalationRule
from app.support.models.tickets import Ticket
from app.services.json_utils import plain_facts
from app.models.execution_status import ExecutionStatus


class EscalationAgent:
    async def escalate_ticket(self, db: AsyncSession, ticket_id: str, tenant_id: str) -> Dict[str, Any]:
        ticket = (await db.execute(
            select(Ticket).where(Ticket.id == ticket_id, Ticket.tenant_id == tenant_id)
        )).scalar_one_or_none()
        if not ticket:
            raise ValueError(f"Ticket {ticket_id} not found")

        # Ground the decision in the tenant's actual escalation policy instead
        # of asking the model to invent a path from scratch - mirrors how
        # SLAAgent grounds itself in SLAPolicy/SLABreach.
        rules = (await db.execute(
            select(EscalationRule).where(
                EscalationRule.tenant_id == tenant_id, EscalationRule.is_active == True  # noqa: E712
            )
        )).scalars().all()

        facts = {
            "subject": ticket.subject,
            "description": (ticket.description or "")[:1500],
            "priority": ticket.priority.value if ticket.priority else None,
            "status": ticket.status.value if ticket.status else None,
            "escalation_policy": [
                {"rule": r.rule_name, "trigger_condition": r.trigger_condition,
                 "time_threshold_mins": r.time_threshold_mins}
                for r in rules
            ],
        }
        facts = plain_facts(facts)
        result = await run_gated_support_skill(
            skill_id="support_escalation",
            steps=[{"step": 1, "name": "Escalate",
                    "prompt": f"Decide the escalation path for this ticket, grounded in "
                              f"the tenant's escalation policy rules (do not invent a "
                              f"policy that isn't listed): {facts}"}],
            context={
                "ticket_id": ticket_id, "tenant_id": tenant_id, **facts,
                # Untrusted customer text under a PII_REDACTION-scanned key so the
                # Luhn/SSN/secret control fires on inbound content (subject/
                # description are not scanned keys). A PAN/SSN here blocks the run
                # at Gate 1, before any escalation record is written.
                "ticket_text": f"{facts.get('subject') or ''}\n{facts.get('description') or ''}",
                # GDPR/CCPA lawful basis for the Gate 6 post-execution audit.
                "legal_basis": "legitimate_interests:customer_support",
                "instruction": "Output strict JSON: {escalate, target_tier, urgency, rationale}.",
            },
            tenant_id=tenant_id,
        )

        # Persist a durable escalation record when the governed decision actually
        # escalated and the run cleared every gate. Without this the escalate
        # action left no trail and /escalation-events never grew past its seed
        # row. A PENDING_HITL / blocked run writes nothing - nothing escalated
        # yet. Mirrors how the other support agents commit on their own session.
        if result.get("status") == ExecutionStatus.SUCCESS_CLEAN:
            decision = extract_decision(result)
            if decision.get("escalate"):
                # The LLM names a tier, not a rule id, so attribute to the
                # tenant's first active escalation rule for rule_id + target.
                rule = rules[0] if rules else None
                db.add(EscalationEvent(
                    tenant_id=tenant_id,
                    ticket_id=ticket_id,
                    rule_id=rule.id if rule else None,
                    escalated_from_agent_id=ticket.assigned_agent_id,
                    escalated_to_agent_id=rule.escalate_to_agent_id if rule else None,
                    reason=decision.get("rationale") or "Escalated by the KAEOS Escalation Agent.",
                ))
                # Make the escalation actually move the ticket when the rule
                # names a target agent (captured escalated_from above first).
                if rule and rule.escalate_to_agent_id:
                    ticket.assigned_agent_id = rule.escalate_to_agent_id
                    db.add(ticket)
                await db.commit()

        return result
