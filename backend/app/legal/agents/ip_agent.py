"""
KAEOS Legal Domain — IP Agent
"""
import logging
from typing import Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.services.llm_router import LLMRouter
from app.legal.models.ip import Patent, IPStatus

logger = logging.getLogger(__name__)

class IPAgent:
    """Agent for monitoring intellectual property registrations and patent drafts."""

    def __init__(self):
        self.router = LLMRouter()
        self.persona = "You are the KAEOS Intellectual Property Agent, specializing in patent law and trademark classification."

    async def evaluate_patentability(self, db: AsyncSession, patent_id: str, tenant_id: str) -> Dict[str, Any]:
        """Evaluates whether a patent abstract meets the non-obviousness criteria for USPTO filing."""
        q = await db.execute(
            select(Patent).where(Patent.id == patent_id, Patent.tenant_id == tenant_id)
        )
        patent = q.scalar_one_or_none()

        if not patent:
            raise ValueError(f"Patent registration {patent_id} not found")

        logger.info(f"IPAgent analyzing patentability of: {patent.title}")

        prompt = f"""
        {self.persona}
        Evaluate this patent application abstract for patentability.
        
        Title: {patent.title}
        Inventors: {patent.inventors}
        Abstract: {patent.abstract}
        
        Output JSON:
        {{
            "is_novel": true,
            "confidence_score": 0.85,
            "prior_art_found": ["No identical prior art found in standard search databases."],
            "recommendation": "File provisional patent application with USPTO."
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

            # Abandoning a patent is irreversible, so it must require an explicit
            # negative — never the mere ABSENCE of a positive signal. A response
            # that omits `is_novel` (or is uncertain) leaves the patent under
            # review rather than silently killing a potentially novel filing.
            novel = result.get("is_novel")
            if novel is True:
                patent.status = IPStatus.ACTIVE
            elif novel is False:
                patent.status = IPStatus.ABANDONED
            # else: unknown — leave status unchanged, keep under review.

            db.add(patent)
            await db.commit()

            return result

        except Exception as e:
            logger.error(f"IP agent patent analysis failed: {e}")
            raise
