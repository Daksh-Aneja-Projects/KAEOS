"""
KAEOS Legal Domain — Governance Agent
"""
import logging
from typing import Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.services.llm_router import LLMRouter
from app.legal.models.core import LegalMatter

logger = logging.getLogger(__name__)

class GovernanceAgent:
    """Agent for monitoring corporate governance and board resolution approvals."""

    def __init__(self):
        self.router = LLMRouter()
        self.persona = "You are the KAEOS Corporate Secretary Agent, specializing in corporate compliance and board structures."

    async def draft_resolution(self, db: AsyncSession, matter_id: str, tenant_id: str) -> Dict[str, Any]:
        """Drafts a board resolution document based on a legal matter description."""
        q = await db.execute(
            select(LegalMatter).where(LegalMatter.id == matter_id, LegalMatter.tenant_id == tenant_id)
        )
        matter = q.scalar_one_or_none()

        if not matter:
            raise ValueError(f"Legal matter {matter_id} not found")

        logger.info(f"GovernanceAgent drafting resolution for matter: {matter.title}")

        prompt = f"""
        {self.persona}
        Draft a corporate board resolution for this matter.
        
        Matter Title: {matter.title}
        Description: {matter.description}
        Type: {matter.matter_type}
        
        Output JSON:
        {{
            "resolution_title": "Resolution of the Board of Directors regarding {matter.title}",
            "draft_text": "WHEREAS, the Corporation has reviewed the matter of {matter.title}... NOW, THEREFORE, BE IT RESOLVED...",
            "governance_status": "DRAFTED",
            "required_approvals": ["Board Chairperson", "General Counsel"]
        }}
        """

        try:
            res = await self.router.complete(prompt=prompt, model_tier="reasoning")
            import json
            content = res if isinstance(res, str) else res.get("content", "{}")
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()

            result = json.loads(content)
            return result

        except Exception as e:
            logger.error(f"Governance agent drafting failed: {e}")
            raise
