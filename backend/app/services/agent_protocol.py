"""
KAEOS S1 N3 — Inter-Agent Communication Protocol
Agent message bus, context passing, circuit breaker, agent discovery.
"""
import logging
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.infrastructure import (
    AgentMessage, AgentMessageStatus, AgentRegistryEntry, ModelTier
)

logger = logging.getLogger(__name__)


class AgentProtocolService:
    """
    N3 — Inter-Agent Communication Protocol
    Manages agent-to-agent messaging, discovery, circuit breaking,
    and context passing across multi-agent workflows.
    """

    # ── Agent Discovery ───────────────────────────────────────────────────

    @staticmethod
    async def register_agent(
        db: AsyncSession,
        tenant_id: str,
        agent_name: str,
        agent_type: str,
        capabilities: list = None,
        model_tier_preference: ModelTier = ModelTier.STANDARD,
        max_concurrent: int = 10
    ) -> dict:
        """Register an agent in the discovery registry."""
        # Check for existing registration
        result = await db.execute(
            select(AgentRegistryEntry).where(
                AgentRegistryEntry.tenant_id == tenant_id,
                AgentRegistryEntry.agent_name == agent_name
            )
        )
        existing = result.scalar_one_or_none()

        if existing:
            existing.capabilities = capabilities or existing.capabilities
            existing.model_tier_preference = model_tier_preference
            existing.max_concurrent = max_concurrent
            existing.health_status = "HEALTHY"
            existing.last_heartbeat = datetime.now(timezone.utc)
            await db.commit()
            entry = existing
        else:
            entry = AgentRegistryEntry(
                tenant_id=tenant_id,
                agent_name=agent_name,
                agent_type=agent_type,
                capabilities=capabilities or [],
                model_tier_preference=model_tier_preference,
                max_concurrent=max_concurrent,
                last_heartbeat=datetime.now(timezone.utc)
            )
            db.add(entry)
            await db.commit()
            await db.refresh(entry)

        logger.info(f"[N3] Agent registered: {agent_name} ({agent_type})")
        return {
            "id": entry.id,
            "agent_name": entry.agent_name,
            "agent_type": entry.agent_type,
            "capabilities": entry.capabilities,
            "health_status": entry.health_status,
            "circuit_state": entry.circuit_state
        }

    @staticmethod
    async def discover_agent(
        db: AsyncSession,
        tenant_id: str,
        capability: str
    ) -> Optional[dict]:
        """Find the best available agent for a given capability."""
        result = await db.execute(
            select(AgentRegistryEntry).where(
                AgentRegistryEntry.tenant_id == tenant_id,
                AgentRegistryEntry.health_status != "OFFLINE",
                AgentRegistryEntry.circuit_state != "OPEN"
            )
        )
        agents = result.scalars().all()

        # Filter by capability
        matching = [a for a in agents if capability in (a.capabilities or [])]
        if not matching:
            return None

        # Select agent with lowest load
        best = min(matching, key=lambda a: a.current_load)
        return {
            "id": best.id,
            "agent_name": best.agent_name,
            "agent_type": best.agent_type,
            "current_load": best.current_load,
            "health_status": best.health_status
        }

    @staticmethod
    async def list_agents(db: AsyncSession, tenant_id: str) -> list:
        """List all registered agents."""
        result = await db.execute(
            select(AgentRegistryEntry)
            .where(AgentRegistryEntry.tenant_id == tenant_id)
            .order_by(AgentRegistryEntry.agent_type, AgentRegistryEntry.agent_name)
        )
        agents = result.scalars().all()
        return [{
            "id": a.id,
            "agent_name": a.agent_name,
            "agent_type": a.agent_type,
            "capabilities": a.capabilities,
            "model_tier_preference": a.model_tier_preference.value if a.model_tier_preference else "STANDARD",
            "current_load": a.current_load,
            "max_concurrent": a.max_concurrent,
            "health_status": a.health_status,
            "circuit_state": a.circuit_state,
            "failure_count": a.failure_count,
            "last_heartbeat": str(a.last_heartbeat) if a.last_heartbeat else None
        } for a in agents]

    # ── Messaging ─────────────────────────────────────────────────────────

    @staticmethod
    async def send_message(
        db: AsyncSession,
        tenant_id: str,
        sender_agent_id: str,
        receiver_agent_id: str,
        message_type: str,
        payload: dict,
        context_envelope: dict = None,
        correlation_id: str = None,
        priority: int = 5,
        ttl_seconds: int = 300
    ) -> dict:
        """Send an async message between agents."""
        msg = AgentMessage(
            tenant_id=tenant_id,
            sender_agent_id=sender_agent_id,
            receiver_agent_id=receiver_agent_id,
            message_type=message_type,
            payload=payload,
            context_envelope=context_envelope or {},
            correlation_id=correlation_id,
            priority=priority,
            ttl_seconds=ttl_seconds
        )
        db.add(msg)
        await db.commit()
        await db.refresh(msg)

        logger.info(f"[N3] Message {msg.id}: {sender_agent_id} → {receiver_agent_id} ({message_type})")
        return {
            "message_id": msg.id,
            "status": msg.status.value,
            "correlation_id": msg.correlation_id
        }

    @staticmethod
    async def receive_messages(
        db: AsyncSession,
        tenant_id: str,
        receiver_agent_id: str,
        limit: int = 20
    ) -> list:
        """Retrieve pending messages for an agent."""
        result = await db.execute(
            select(AgentMessage).where(
                AgentMessage.tenant_id == tenant_id,
                AgentMessage.receiver_agent_id == receiver_agent_id,
                AgentMessage.status == AgentMessageStatus.PENDING
            )
            .order_by(AgentMessage.priority, AgentMessage.created_at)
            .limit(limit)
        )
        messages = result.scalars().all()

        # Mark as delivered
        for m in messages:
            m.status = AgentMessageStatus.DELIVERED
            m.delivered_at = datetime.now(timezone.utc)
        await db.commit()

        return [{
            "id": m.id,
            "sender_agent_id": m.sender_agent_id,
            "message_type": m.message_type,
            "payload": m.payload,
            "context_envelope": m.context_envelope,
            "correlation_id": m.correlation_id,
            "priority": m.priority,
            "created_at": str(m.created_at) if m.created_at else None
        } for m in messages]

    @staticmethod
    async def acknowledge_message(
        db: AsyncSession,
        message_id: str,
        success: bool = True
    ):
        """Acknowledge a processed message."""
        result = await db.execute(
            select(AgentMessage).where(AgentMessage.id == message_id)
        )
        msg = result.scalar_one_or_none()
        if msg:
            msg.status = AgentMessageStatus.PROCESSED if success else AgentMessageStatus.FAILED
            msg.processed_at = datetime.now(timezone.utc)
            await db.commit()

    # ── Circuit Breaker ───────────────────────────────────────────────────

    @staticmethod
    async def record_failure(
        db: AsyncSession,
        tenant_id: str,
        agent_name: str
    ) -> dict:
        """Record a failure for circuit breaker logic."""
        result = await db.execute(
            select(AgentRegistryEntry).where(
                AgentRegistryEntry.tenant_id == tenant_id,
                AgentRegistryEntry.agent_name == agent_name
            )
        )
        agent = result.scalar_one_or_none()
        if not agent:
            return {"error": "agent_not_found"}

        agent.failure_count += 1
        agent.last_failure_at = datetime.now(timezone.utc)

        if agent.failure_count >= agent.failure_threshold:
            agent.circuit_state = "OPEN"
            agent.health_status = "DEGRADED"
            logger.warning(f"[N3] Circuit OPEN for agent {agent_name} after {agent.failure_count} failures")

        await db.commit()
        return {
            "agent_name": agent_name,
            "circuit_state": agent.circuit_state,
            "failure_count": agent.failure_count
        }

    @staticmethod
    async def reset_circuit(
        db: AsyncSession,
        tenant_id: str,
        agent_name: str
    ):
        """Reset circuit breaker for an agent."""
        result = await db.execute(
            select(AgentRegistryEntry).where(
                AgentRegistryEntry.tenant_id == tenant_id,
                AgentRegistryEntry.agent_name == agent_name
            )
        )
        agent = result.scalar_one_or_none()
        if agent:
            agent.circuit_state = "CLOSED"
            agent.failure_count = 0
            agent.health_status = "HEALTHY"
            await db.commit()

    @staticmethod
    async def heartbeat(
        db: AsyncSession,
        tenant_id: str,
        agent_name: str,
        current_load: int = 0
    ):
        """Update agent heartbeat and load."""
        result = await db.execute(
            select(AgentRegistryEntry).where(
                AgentRegistryEntry.tenant_id == tenant_id,
                AgentRegistryEntry.agent_name == agent_name
            )
        )
        agent = result.scalar_one_or_none()
        if agent:
            agent.last_heartbeat = datetime.now(timezone.utc)
            agent.current_load = current_load
            # Auto half-open circuit after heartbeat
            if agent.circuit_state == "OPEN":
                agent.circuit_state = "HALF_OPEN"
            await db.commit()

    @staticmethod
    async def get_message_history(
        db: AsyncSession,
        tenant_id: str,
        correlation_id: str = None,
        limit: int = 50
    ) -> list:
        """Get message history, optionally filtered by correlation ID."""
        query = select(AgentMessage).where(
            AgentMessage.tenant_id == tenant_id
        )
        if correlation_id:
            query = query.where(AgentMessage.correlation_id == correlation_id)
        query = query.order_by(AgentMessage.created_at.desc()).limit(limit)

        result = await db.execute(query)
        messages = result.scalars().all()
        return [{
            "id": m.id,
            "sender_agent_id": m.sender_agent_id,
            "receiver_agent_id": m.receiver_agent_id,
            "message_type": m.message_type,
            "status": m.status.value,
            "priority": m.priority,
            "created_at": str(m.created_at) if m.created_at else None,
            "delivered_at": str(m.delivered_at) if m.delivered_at else None,
            "processed_at": str(m.processed_at) if m.processed_at else None
        } for m in messages]
