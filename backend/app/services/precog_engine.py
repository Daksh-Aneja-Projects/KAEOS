"""
KAEOS 10X — Pre-Cog Engine (L24)
Zero-Prompt Asynchronous Autonomous Intelligence
"""
import logging
import asyncio
from datetime import datetime, timezone
from typing import Dict, Any, List

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.domain import Rule, DecayEvent
# Note: In a fully integrated system, this imports Bidder models,
# establishing cross-repository awareness for the L24 implementation.

logger = logging.getLogger(__name__)

class PreCogEngine:
    """
    L24 Asynchronous Ambient Intelligence.
    Runs 24/7 monitoring external signals (News, Macro-economics, Competitor actions).
    If a shift is detected, it autonomously recalculates models across active bids.
    """
    
    def __init__(self):
        self.is_running = False
        
    async def _monitor_external_signals(self, db: AsyncSession, tenant_id: str | None = None) -> List[Dict[str, Any]]:
        """Queries the L1 Data Fabric for unhandled high-authority macroeconomic signals.

        When tenant_id is provided (route-triggered), results are scoped to that
        tenant; the ambient background loop passes None to sweep all tenants.
        """
        from app.models.domain import Signal

        # Fetch unprocessed macro signals with authority > 0.8
        signal_q_stmt = (
            select(Signal)
            .where(Signal.signal_type == "MACRO_ECONOMIC_SHIFT")
            .where(Signal.authority_score > 0.8)
            .where(Signal.processed_at == None)  # noqa: E711
        )
        if tenant_id is not None:
            signal_q_stmt = signal_q_stmt.where(Signal.tenant_id == tenant_id)
        signal_q = await db.execute(signal_q_stmt)
        recent_signals = signal_q.scalars().all()

        parsed_signals = []
        now = datetime.now(timezone.utc)
        for s in recent_signals:
            parsed_signals.append({
                "signal_id": s.id,
                "type": s.signal_type,
                "source": s.source_type,
                "summary": s.clean_payload,
                "affected_domains": s.entities if isinstance(s.entities, list) else [],
                "timestamp": s.created_at.isoformat() if s.created_at else now.isoformat()
            })

            # Mark as processed using proper timestamp field (not by mutating authority_score)
            s.processed_at = now
            db.add(s)

        if parsed_signals:
            await db.commit()

        return parsed_signals


    async def _recalculate_active_bids(self, db: AsyncSession, signal: Dict[str, Any], tenant_id: str | None = None):
        """Autonomously adjusts rules and flags margin risk before human intervention.

        When tenant_id is provided, only that tenant's rules are decayed; the
        ambient loop passes None to operate across all tenants.
        """
        logger.warning(f"L24 Pre-Cog: Waking up due to signal: {signal['summary']}")

        # 1. Update the Polystore Knowledge Graph
        # We find commercial rules related to Europe/Pricing and immediately apply a decay/adjustment.
        rule_q_stmt = select(Rule).where(Rule.domain == "commercial_sales")
        if tenant_id is not None:
            rule_q_stmt = rule_q_stmt.where(Rule.tenant_id == tenant_id)
        rule_q = await db.execute(rule_q_stmt)
        commercial_rules = rule_q.scalars().all()
        
        from app.services.llm_router import LLMRouter
        import json
        router = LLMRouter()
        
        adjusted_count = 0
        for rule in commercial_rules:
            # Pre-Cog autonomously evaluates impact of the signal on the specific rule
            prompt = (
                f"Macro Signal: {signal['summary']}\n"
                f"Rule: {rule.statement}\n"
                f"Does this macroeconomic signal negatively impact the confidence of this rule? Output JSON: {{\"impacted\": true/false, \"decay_factor\": 0.85}}"
            )
            try:
                res = await router.complete(prompt=prompt, model_tier="fast")
                content = res if isinstance(res, str) else res.get("content", "{}")
                analysis = json.loads(content) if isinstance(content, str) else content
                if analysis.get("impacted"):
                    decay = analysis.get("decay_factor", 0.85)
                    old_conf = rule.confidence_scalar
                    rule.confidence_scalar *= decay
                    rule.confidence_tier = "SPECULATIVE"
                    
                    event = DecayEvent(
                        tenant_id=rule.tenant_id,
                        rule_id=rule.id,
                        event_type="PRECOG_MACRO_INTERVENTION",
                        trigger_source=signal["source"],
                        confidence_before=old_conf,
                        confidence_after=rule.confidence_scalar,
                        action_taken="ELICITATION_TRIGGERED"
                    )
                    db.add(event)
                    adjusted_count += 1
            except Exception as e:
                logger.error(f"L24 Pre-Cog evaluation failed for rule {rule.id}: {e}")
                
        if adjusted_count > 0:
            await db.commit()
            logger.info(f"L24 Pre-Cog: Generatively recalculated {adjusted_count} rules based on macro signal. DecayEvents generated.")
            
    async def run_ambient_loop(self):
        """The continuous 24/7 ambient loop."""
        self.is_running = True
        logger.info("L24 Pre-Cog Engine initialized and running in ambient background mode.")
        
        while self.is_running:
            try:
                async with AsyncSessionLocal() as db:
                    signals = await self._monitor_external_signals(db)
                    if signals:
                        for sig in signals:
                            await self._recalculate_active_bids(db, sig)
                            
                # Sleep for 1 hour before checking again
                await asyncio.sleep(3600)
            except asyncio.CancelledError:
                self.is_running = False
                logger.info("L24 Pre-Cog Engine shut down.")
                break
            except Exception as e:
                logger.error(f"L24 Pre-Cog Engine error: {e}")
                await asyncio.sleep(60)

# To start the engine, the main FastAPI app lifecycle would call:
# asyncio.create_task(PreCogEngine().run_ambient_loop())
