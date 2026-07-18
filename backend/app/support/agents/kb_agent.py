"""
KAEOS Support Domain — KB Agent
"""
import logging
import json
from typing import Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.services.llm_router import LLMRouter
from app.support.models.tickets import Ticket, TicketComment
from app.support.models.knowledge import KBArticle

logger = logging.getLogger(__name__)

class KBAgent:
    """Agent for auto-drafting knowledge articles from resolved ticket logs."""

    def __init__(self):
        self.router = LLMRouter()
        self.persona = "You are the KAEOS Knowledge Base Curator Agent, dedicated to technical writing and documentation."

    async def document_resolution(self, db: AsyncSession, ticket_id: str, tenant_id: str) -> Dict[str, Any]:
        """Examines a resolved ticket's details and resolution text to draft a reusable FAQ article."""
        q = await db.execute(select(Ticket).where(Ticket.id == ticket_id, Ticket.tenant_id == tenant_id))
        ticket = q.scalar_one_or_none()

        if not ticket:
            raise ValueError(f"Ticket {ticket_id} not found")

        logger.info(f"KBAgent documenting resolution for ticket: #{ticket.ticket_number}")

        # Fetch comments
        comments_q = await db.execute(select(TicketComment).where(
            TicketComment.ticket_id == ticket_id, TicketComment.tenant_id == tenant_id
        ))
        comments = comments_q.scalars().all()
        history = "\n".join([f"{c.author_type}: {c.body}" for c in comments])

        prompt = f"""
        {self.persona}
        Convert this support conversation history into a reusable, structured knowledge base FAQ article in Markdown.
        
        Ticket Subject: {ticket.subject}
        Description: {ticket.description}
        
        Comments:
        {history}
        
        Output JSON:
        {{
            "article_title": "How to resolve: {ticket.subject}",
            "content_markdown": "# Troubleshooting {ticket.subject}\\n\\n## Issue\\n...\\n\\n## Resolution\\n...",
            "categories": ["technical_faq"]
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

            import uuid
            article = KBArticle(
                id=str(uuid.uuid4()),
                tenant_id=ticket.tenant_id,
                title=result.get("article_title", f"FAQ: {ticket.subject}"),
                content_md=result.get("content_markdown", "No content drafted."),
                is_published=False,
                views=0
            )
            db.add(article)
            await db.commit()

            return result

        except Exception as e:
            logger.error(f"KB agent documentation failed: {e}")
            raise
