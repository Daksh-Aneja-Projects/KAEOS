"""
KAEOS Workforce Layer — Enterprise Memory Engine

Distills organizational knowledge from agent actions.
"""
import logging
from sqlalchemy.ext.asyncio import AsyncSession
from app.workforce.models.memory import DecisionLog

logger = logging.getLogger(__name__)

class EnterpriseMemoryEngine:
    
    @staticmethod
    async def log_decision(db: AsyncSession, tenant_id: str, dept_id: str, agent_id: str, decision_data: dict) -> DecisionLog:
        """Logs an immutable agent decision."""
        log = DecisionLog(
            tenant_id=tenant_id,
            department_id=dept_id,
            agent_id=agent_id,
            decision_type=decision_data.get("type", "generic"),
            question=decision_data.get("question", ""),
            answer=decision_data.get("answer", ""),
            reasoning_chain=decision_data.get("reasoning", []),
            confidence=decision_data.get("confidence", 1.0)
        )
        db.add(log)
        await db.commit()
        return log
