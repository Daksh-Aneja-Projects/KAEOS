"""
KAEOS S1 N2 — Inference Cost Governor Service
Token budget allocation, real-time cost telemetry, budget enforcement, cost attribution.
"""
import logging
from datetime import datetime, timezone, timedelta
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.infrastructure import TokenBudget, CostEvent

logger = logging.getLogger(__name__)


class CostGovernorService:
    """
    N2 — Inference Cost Governor
    Assigns token budgets per tenant/agent/workflow, tracks real-time cost,
    enforces soft/hard limits, and attributes costs to business outcomes.
    """

    @staticmethod
    async def create_budget(
        db: AsyncSession,
        tenant_id: str,
        scope: str = "tenant",
        scope_id: str = None,
        period: str = "monthly",
        token_limit: int = 10_000_000,
        cost_limit_usd: float = 100.0,
        soft_limit_pct: float = 0.80,
        hard_limit_pct: float = 0.95
    ) -> dict:
        """Create or update a token budget allocation."""
        # Check for existing budget
        query = select(TokenBudget).where(
            TokenBudget.tenant_id == tenant_id,
            TokenBudget.scope == scope
        )
        if scope_id:
            query = query.where(TokenBudget.scope_id == scope_id)
        result = await db.execute(query)
        existing = result.scalar_one_or_none()

        if existing:
            existing.token_limit = token_limit
            existing.cost_limit_usd = cost_limit_usd
            existing.soft_limit_pct = soft_limit_pct
            existing.hard_limit_pct = hard_limit_pct
            await db.commit()
            budget = existing
        else:
            budget = TokenBudget(
                tenant_id=tenant_id,
                scope=scope,
                scope_id=scope_id,
                period=period,
                token_limit=token_limit,
                cost_limit_usd=cost_limit_usd,
                soft_limit_pct=soft_limit_pct,
                hard_limit_pct=hard_limit_pct
            )
            db.add(budget)
            await db.commit()
            await db.refresh(budget)

        return {
            "id": budget.id,
            "scope": budget.scope,
            "scope_id": budget.scope_id,
            "token_limit": budget.token_limit,
            "cost_limit_usd": budget.cost_limit_usd,
            "token_used": budget.token_used,
            "cost_used_usd": budget.cost_used_usd
        }

    @staticmethod
    async def check_budget(
        db: AsyncSession,
        tenant_id: str,
        estimated_tokens: int = 0,
        scope: str = "tenant",
        scope_id: str = None
    ) -> dict:
        """
        Check if a request is within budget.
        Returns enforcement action: ALLOW, WARN, DEGRADE, BLOCK.
        """
        query = select(TokenBudget).where(
            TokenBudget.tenant_id == tenant_id,
            TokenBudget.scope == scope
        )
        if scope_id:
            query = query.where(TokenBudget.scope_id == scope_id)
        result = await db.execute(query)
        budget = result.scalar_one_or_none()

        if not budget:
            return {"action": "ALLOW", "reason": "no_budget_configured", "usage_pct": 0}

        projected = budget.token_used + estimated_tokens
        usage_pct = projected / max(budget.token_limit, 1)
        cost_pct = budget.cost_used_usd / max(budget.cost_limit_usd, 0.01)

        effective_pct = max(usage_pct, cost_pct)

        if effective_pct >= budget.hard_limit_pct:
            action = budget.enforcement_action  # DEGRADE, QUEUE, or BLOCK
        elif effective_pct >= budget.soft_limit_pct:
            action = "WARN"
        else:
            action = "ALLOW"

        return {
            "action": action,
            "usage_pct": round(effective_pct * 100, 1),
            "tokens_remaining": max(0, budget.token_limit - budget.token_used),
            "cost_remaining_usd": round(max(0, budget.cost_limit_usd - budget.cost_used_usd), 4),
            "budget_id": budget.id
        }

    @staticmethod
    async def record_usage(
        db: AsyncSession,
        tenant_id: str,
        model_name: str,
        model_tier: str,
        input_tokens: int,
        output_tokens: int,
        cost_usd: float,
        latency_ms: int = 0,
        agent_id: str = None,
        workflow_id: str = None,
        skill_id: str = None,
        execution_id: str = None,
        request_type: str = None,
        success: bool = True
    ) -> dict:
        """Record a token consumption event and update budget counters."""
        total_tokens = input_tokens + output_tokens

        # Log cost event
        event = CostEvent(
            tenant_id=tenant_id,
            model_name=model_name,
            model_tier=model_tier,
            agent_id=agent_id,
            workflow_id=workflow_id,
            skill_id=skill_id,
            execution_id=execution_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            cost_usd=cost_usd,
            latency_ms=latency_ms,
            request_type=request_type,
            success=success
        )
        db.add(event)

        # Update budget counters with row-level lock to prevent TOCTOU races.
        result = await db.execute(
            select(TokenBudget)
            .where(
                TokenBudget.tenant_id == tenant_id,
                TokenBudget.scope == "tenant"
            )
            .with_for_update()
        )
        budget = result.scalar_one_or_none()
        if budget:
            budget.token_used += total_tokens
            budget.cost_used_usd += cost_usd

        await db.commit()
        return {
            "event_id": event.id,
            "total_tokens": total_tokens,
            "cost_usd": cost_usd
        }

    @staticmethod
    async def get_cost_telemetry(
        db: AsyncSession,
        tenant_id: str,
        hours: int = 24
    ) -> dict:
        """Real-time cost telemetry: token consumption per model, agent, workflow."""
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

        result = await db.execute(
            select(CostEvent).where(
                CostEvent.tenant_id == tenant_id,
                CostEvent.timestamp >= cutoff
            ).order_by(CostEvent.timestamp.desc())
        )
        events = result.scalars().all()

        # Aggregate by model tier
        tier_agg = {}
        agent_agg = {}
        type_agg = {}
        total_tokens = 0
        total_cost = 0.0

        for e in events:
            total_tokens += e.total_tokens
            total_cost += e.cost_usd

            tier_agg.setdefault(e.model_tier, {"tokens": 0, "cost": 0.0, "calls": 0})
            tier_agg[e.model_tier]["tokens"] += e.total_tokens
            tier_agg[e.model_tier]["cost"] += e.cost_usd
            tier_agg[e.model_tier]["calls"] += 1

            if e.agent_id:
                agent_agg.setdefault(e.agent_id, {"tokens": 0, "cost": 0.0, "calls": 0})
                agent_agg[e.agent_id]["tokens"] += e.total_tokens
                agent_agg[e.agent_id]["cost"] += e.cost_usd
                agent_agg[e.agent_id]["calls"] += 1

            if e.request_type:
                type_agg.setdefault(e.request_type, {"tokens": 0, "cost": 0.0, "calls": 0})
                type_agg[e.request_type]["tokens"] += e.total_tokens
                type_agg[e.request_type]["cost"] += e.cost_usd
                type_agg[e.request_type]["calls"] += 1

        # Get budget status
        budget_result = await db.execute(
            select(TokenBudget).where(
                TokenBudget.tenant_id == tenant_id,
                TokenBudget.scope == "tenant"
            )
        )
        budget = budget_result.scalar_one_or_none()

        return {
            "period_hours": hours,
            "total_tokens": total_tokens,
            "total_cost_usd": round(total_cost, 4),
            "total_events": len(events),
            "avg_cost_per_task": round(total_cost / max(len(events), 1), 4),
            "by_tier": {k: {**v, "cost": round(v["cost"], 4)} for k, v in tier_agg.items()},
            "by_agent": {k: {**v, "cost": round(v["cost"], 4)} for k, v in agent_agg.items()},
            "by_request_type": {k: {**v, "cost": round(v["cost"], 4)} for k, v in type_agg.items()},
            "budget": {
                "token_limit": budget.token_limit if budget else None,
                "token_used": budget.token_used if budget else 0,
                "cost_limit_usd": budget.cost_limit_usd if budget else None,
                "cost_used_usd": round(budget.cost_used_usd, 4) if budget else 0,
                "usage_pct": round((budget.token_used / max(budget.token_limit, 1)) * 100, 1) if budget else 0
            }
        }

    @staticmethod
    async def get_budgets(db: AsyncSession, tenant_id: str) -> list:
        """List all budgets for a tenant."""
        result = await db.execute(
            select(TokenBudget).where(TokenBudget.tenant_id == tenant_id)
            .order_by(TokenBudget.scope)
        )
        budgets = result.scalars().all()
        return [{
            "id": b.id,
            "scope": b.scope,
            "scope_id": b.scope_id,
            "period": b.period,
            "token_limit": b.token_limit,
            "token_used": b.token_used,
            "cost_limit_usd": b.cost_limit_usd,
            "cost_used_usd": round(b.cost_used_usd, 4),
            "usage_pct": round((b.token_used / max(b.token_limit, 1)) * 100, 1),
            "soft_limit_pct": b.soft_limit_pct,
            "hard_limit_pct": b.hard_limit_pct,
            "enforcement_action": b.enforcement_action
        } for b in budgets]
