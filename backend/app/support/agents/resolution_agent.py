"""KAEOS Support Domain — Resolution Agent

Matches a ticket against the published knowledge base and drafts a customer
reply THROUGH the gate pipeline (compliance/PII, fairness, the confidence/HITL
dial, debate, audit, provenance) — the same ``run_gated_support_skill`` path
every other support agent uses.

This agent used to call the LLM raw and then set ``ticket.status = RESOLVED``
whenever the model's own JSON said ``resolved`` with ``confidence > 0.85`` —
the model's self-reported confidence was the authority, which is exactly the
premise Gate 3 exists to reject (it caps confidence at the tenant's probed
ceiling). The agent now only recommends: the draft is filed as an internal
comment when the governed run succeeds, and ticket state changes remain a
human (or governed-transition) action.
"""
import logging
import uuid
from typing import Any, Dict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.execution_status import SUCCEEDED_STATUSES
from app.services.json_utils import plain_facts
from app.support.agents.gated_runner import extract_decision, run_gated_support_skill
from app.support.models.knowledge import KBArticle
from app.support.models.tickets import Ticket, TicketComment

logger = logging.getLogger(__name__)


class ResolutionAgent:
    """Agent for matching tickets against knowledge base and drafting customer replies."""

    async def solve_ticket(self, db: AsyncSession, ticket_id: str, tenant_id: str) -> Dict[str, Any]:
        """Governed KB-match + reply draft. Recommends resolution; never closes."""
        q = await db.execute(select(Ticket).where(Ticket.id == ticket_id, Ticket.tenant_id == tenant_id))
        ticket = q.scalar_one_or_none()
        if not ticket:
            raise ValueError(f"Ticket {ticket_id} not found")

        logger.info(f"ResolutionAgent processing ticket: #{ticket.ticket_number}")

        # Published KB articles only; tenant filter is load-bearing (content is
        # inlined into the prompt and can surface in the drafted reply).
        kb_q = await db.execute(select(KBArticle).where(
            KBArticle.is_published == True, KBArticle.tenant_id == tenant_id  # noqa: E712
        ).limit(10))
        articles = kb_q.scalars().all()
        kb_context = "\n".join(
            f"Article: {a.title}\nContent:\n{(a.content_md or '')[:1000]}" for a in articles
        )

        facts = plain_facts({
            "subject": ticket.subject,
            "description": (ticket.description or "")[:1500],
            "priority": ticket.priority.value if ticket.priority else None,
            "status": ticket.status.value if ticket.status else None,
        })

        result = await run_gated_support_skill(
            skill_id="support_ticket_resolution",
            steps=[{
                "step": 1, "name": "Resolve",
                "prompt": (
                    "Evaluate whether any of these published knowledge-base articles "
                    f"resolves the ticket, and draft a customer reply.\n"
                    f"Ticket: {facts}\n\nAvailable KB Articles:\n{kb_context}"
                ),
            }],
            context={
                "ticket_id": ticket_id, "tenant_id": tenant_id, **facts,
                # Untrusted customer text under the key the PII_REDACTION
                # checker scans (see AutoResolveAgent for why this is explicit).
                "ticket_text": f"{facts.get('subject') or ''}\n{facts.get('description') or ''}",
                "legal_basis": "contract:support_response",
                "instruction": ("Output strict JSON: {resolved, article_matched, "
                                "confidence, draft_reply}."),
            },
            tenant_id=tenant_id,
        )

        decision = extract_decision(result)
        succeeded = (result.get("status") or "") in SUCCEEDED_STATUSES
        if succeeded and decision.get("draft_reply"):
            db.add(TicketComment(
                id=str(uuid.uuid4()),
                tenant_id=ticket.tenant_id,
                ticket_id=ticket.id,
                author_type="AGENT",
                author_id="resolution_agent",
                body=str(decision.get("draft_reply")),
                is_internal="Yes",
            ))
            await db.commit()

        return {
            **result,
            "resolved": bool(decision.get("resolved")) if succeeded else False,
            "article_matched": decision.get("article_matched") if succeeded else None,
            "draft_reply": decision.get("draft_reply") if succeeded else None,
            # The agent recommends; a human (or a governed transition) closes.
            "recommendation_only": True,
        }
