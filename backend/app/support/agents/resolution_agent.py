"""
KAEOS Support Domain — Resolution Agent
"""
import logging
import json
from typing import Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.services.llm_router import LLMRouter
from app.support.models.tickets import Ticket, TicketComment, TicketStatus
from app.support.models.knowledge import KBArticle

logger = logging.getLogger(__name__)

class ResolutionAgent:
    """Agent for matching tickets against knowledge base and drafting customer replies."""

    def __init__(self):
        self.router = LLMRouter()
        self.persona = "You are the KAEOS Support Resolution Agent, an expert in troubleshooting and customer service."

    async def solve_ticket(self, db: AsyncSession, ticket_id: str, tenant_id: str) -> Dict[str, Any]:
        """Resolves ticket by retrieving published KB articles and using them to formulate a drafted response."""
        q = await db.execute(select(Ticket).where(Ticket.id == ticket_id, Ticket.tenant_id == tenant_id))
        ticket = q.scalar_one_or_none()

        if not ticket:
            raise ValueError(f"Ticket {ticket_id} not found")

        logger.info(f"ResolutionAgent processing ticket: #{ticket.ticket_number}")

        # Fetch knowledge articles. Tenant filter is load-bearing: these are
        # inlined into the prompt and can surface in the drafted customer reply.
        kb_q = await db.execute(select(KBArticle).where(
            KBArticle.is_published == True, KBArticle.tenant_id == tenant_id  # noqa: E712
        ))
        articles = kb_q.scalars().all()

        kb_context = "\n".join([f"Article: {art.title}\nContent:\n{art.content_md}" for art in articles])

        prompt = f"""
        {self.persona}
        Evaluate if any of the following knowledge base articles can resolve the user's issue.
        If a solution matches, draft a reply to the customer.
        
        Ticket Subject: {ticket.subject}
        Description: {ticket.description}
        
        Available KB Articles:
        {kb_context}
        
        Provide your solution in JSON:
        {{
            "resolved": true,
            "article_matched": "Article Title or None",
            "confidence": 0.90,
            "draft_reply": "Hello, thank you for reaching out. Based on our FAQ, to reset your password..."
        }}
        """

        try:
            res = await self.router.complete(prompt=prompt, model_tier="reasoning")
            content = res if isinstance(res, str) else res.get("content", "{}")
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()

            result = json.loads(content)

            # Record internal comment with drafted reply
            import uuid
            comment = TicketComment(
                id=str(uuid.uuid4()),
                tenant_id=ticket.tenant_id,
                ticket_id=ticket.id,
                author_type="AGENT",
                author_id="resolution_agent",
                body=result.get("draft_reply", "Unable to draft response."),
                is_internal="Yes"
            )
            db.add(comment)
            
            if result.get("resolved") and result.get("confidence", 0) > 0.85:
                ticket.status = TicketStatus.RESOLVED
                db.add(ticket)

            await db.commit()

            return result

        except Exception as e:
            logger.error(f"Support resolution agent failed: {e}")
            raise
