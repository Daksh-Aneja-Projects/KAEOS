"""KAEOS Support Domain — KB Agent

Drafts a reusable knowledge-base article from a resolved ticket's history
THROUGH the gate pipeline (previously a raw LLM call that wrote the article
with no compliance/PII gate, no audit, no provenance — the only mitigation
was ``is_published=False``). The draft persists only when the governed run
succeeds, and it always lands unpublished for human review.
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


class KBAgent:
    """Agent for auto-drafting knowledge articles from resolved ticket logs."""

    async def document_resolution(self, db: AsyncSession, ticket_id: str, tenant_id: str) -> Dict[str, Any]:
        """Governed FAQ draft from a ticket's conversation history."""
        q = await db.execute(select(Ticket).where(Ticket.id == ticket_id, Ticket.tenant_id == tenant_id))
        ticket = q.scalar_one_or_none()
        if not ticket:
            raise ValueError(f"Ticket {ticket_id} not found")

        logger.info(f"KBAgent documenting resolution for ticket: #{ticket.ticket_number}")

        comments_q = await db.execute(select(TicketComment).where(
            TicketComment.ticket_id == ticket_id, TicketComment.tenant_id == tenant_id
        ).limit(30))
        comments = comments_q.scalars().all()
        history = "\n".join(f"{c.author_type}: {(c.body or '')[:800]}" for c in comments)

        facts = plain_facts({
            "subject": ticket.subject,
            "description": (ticket.description or "")[:1500],
        })

        result = await run_gated_support_skill(
            skill_id="support_kb_draft",
            steps=[{
                "step": 1, "name": "Document",
                "prompt": (
                    "Convert this support conversation into a reusable, structured "
                    f"knowledge-base FAQ article in Markdown.\nTicket: {facts}\n\n"
                    f"Comments:\n{history}"
                ),
            }],
            context={
                "ticket_id": ticket_id, "tenant_id": tenant_id, **facts,
                # Conversation history is untrusted content — expose it under the
                # key the PII_REDACTION checker scans so the CRIT control runs.
                "ticket_text": f"{facts.get('subject') or ''}\n{facts.get('description') or ''}\n{history}",
                "legal_basis": "legitimate_interest:knowledge_documentation",
                "instruction": ("Output strict JSON: {article_title, "
                                "content_markdown, categories}."),
            },
            tenant_id=tenant_id,
        )

        decision = extract_decision(result)
        succeeded = (result.get("status") or "") in SUCCEEDED_STATUSES
        article_id = None
        if succeeded and decision.get("content_markdown"):
            article_id = str(uuid.uuid4())
            db.add(KBArticle(
                id=article_id,
                tenant_id=ticket.tenant_id,
                title=str(decision.get("article_title") or f"FAQ: {ticket.subject}"),
                content_md=str(decision.get("content_markdown")),
                is_published=False,   # always lands unpublished, for human review
                views=0,
            ))
            await db.commit()

        return {**result, "article_id": article_id,
                "article_title": decision.get("article_title") if succeeded else None}
